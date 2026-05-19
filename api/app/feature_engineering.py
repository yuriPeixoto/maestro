"""
Feature engineering pipeline for Maestro ML (Phase 3).

Transforms raw metric data stored in ClickHouse into ML-ready features and
persists them in the metric_features table. Runs as a FastAPI background task:
once at startup to backfill recent history, then every hour.

Features computed per (server_id, metric_name, timestamp):
  - rolling_mean_5m, rolling_std_5m  — smoothed signal + volatility
  - rate_of_change                   — sudden-jump detector
  - hour_sin, hour_cos               — cyclic hour-of-day (unit circle)
  - day_of_week, is_weekend          — weekly seasonality
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_PIPELINE_INTERVAL_SECONDS = 3600  # re-run every hour
_LOOKBACK_DAYS = 30                # backfill window on first run
_ROLLING_BUFFER_MINUTES = 10       # extra history fetched to warm up rolling windows


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class FeatureRow:
    server_id: str
    metric_name: str
    timestamp: datetime
    raw_value: float
    rolling_mean_5m: float
    rolling_std_5m: float
    rate_of_change: float
    hour_sin: float
    hour_cos: float
    day_of_week: int
    is_weekend: int


# ── Pure computation (no I/O — fully unit-testable) ───────────────────────────

def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute ML features from a raw metric time series.

    Args:
        df: DataFrame with columns [timestamp, value].
            timestamp must be tz-aware (UTC). Rows need not be sorted.

    Returns:
        DataFrame with original columns plus all feature columns.
        Rows are sorted by timestamp ascending.
    """
    if df.empty:
        return df

    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    df = df.set_index("timestamp")

    # Rolling 5-minute statistics
    rolling = df["value"].rolling("5min", min_periods=1)
    df["rolling_mean_5m"] = rolling.mean()
    df["rolling_std_5m"] = rolling.std().fillna(0.0)

    # Rate of change: Δvalue / Δseconds (zero for the first row)
    elapsed_s = df.index.to_series().diff().dt.total_seconds()
    df["rate_of_change"] = (df["value"].diff() / elapsed_s).fillna(0.0)

    # Cyclic hour-of-day encoding
    hour_frac = df.index.hour + df.index.minute / 60 + df.index.second / 3600
    radians = 2 * math.pi * hour_frac / 24
    df["hour_sin"] = np.sin(radians)
    df["hour_cos"] = np.cos(radians)

    # Day-of-week features (Monday=0, Sunday=6)
    df["day_of_week"] = df.index.dayofweek.astype(np.uint8)
    df["is_weekend"] = (df.index.dayofweek >= 5).astype(np.uint8)

    df["raw_value"] = df["value"]
    return df.reset_index()


def dataframe_to_feature_rows(
    server_id: str,
    metric_name: str,
    df: pd.DataFrame,
    after: datetime | None,
) -> list[FeatureRow]:
    """
    Convert a feature DataFrame to FeatureRow dataclass instances,
    filtering to only rows with timestamp strictly after `after`.
    """
    rows: list[FeatureRow] = []
    for row in df.itertuples(index=False):
        ts: datetime = row.timestamp
        if not ts.tzinfo:
            ts = ts.replace(tzinfo=timezone.utc)
        if after is not None and ts <= after:
            continue
        rows.append(FeatureRow(
            server_id=server_id,
            metric_name=metric_name,
            timestamp=ts,
            raw_value=float(row.raw_value),
            rolling_mean_5m=float(row.rolling_mean_5m),
            rolling_std_5m=float(row.rolling_std_5m),
            rate_of_change=float(row.rate_of_change),
            hour_sin=float(row.hour_sin),
            hour_cos=float(row.hour_cos),
            day_of_week=int(row.day_of_week),
            is_weekend=int(row.is_weekend),
        ))
    return rows


# ── Async pipeline ────────────────────────────────────────────────────────────

async def _process_server_metric(
    reader,
    writer,
    server_id: str,
    metric_name: str,
) -> int:
    """
    Process one (server_id, metric_name) pair: fetch raw metrics since the
    last watermark, compute features, and insert new rows.

    Returns the number of feature rows inserted.
    """
    watermark: datetime | None = await reader.get_feature_watermark(server_id, metric_name)

    if watermark is None:
        since = datetime.now(tz=timezone.utc) - timedelta(days=_LOOKBACK_DAYS)
    else:
        since = watermark - timedelta(minutes=_ROLLING_BUFFER_MINUTES)

    raw = await reader.get_metrics_range(server_id, metric_name, since)
    if not raw:
        return 0

    df = pd.DataFrame(raw, columns=["timestamp", "value"])
    df = compute_features(df)
    if df.empty:
        return 0

    feature_rows = dataframe_to_feature_rows(server_id, metric_name, df, after=watermark)
    if not feature_rows:
        return 0

    await writer.insert_feature_batch(feature_rows)
    return len(feature_rows)


async def run_feature_pipeline(reader, writer) -> None:
    """
    Background task: compute and persist ML features for all servers and metrics.
    Runs once at startup (backfill), then every hour.
    """
    logger.info("feature-pipeline: starting")
    while True:
        try:
            servers = await reader.get_known_server_ids()
            total = 0
            for server_id in servers:
                metric_names = await reader.get_metric_names(server_id)
                for metric_name in metric_names:
                    inserted = await _process_server_metric(reader, writer, server_id, metric_name)
                    total += inserted
            if total:
                logger.info("feature-pipeline: inserted %d feature rows across %d servers",
                            total, len(servers))
            else:
                logger.debug("feature-pipeline: no new data to process")
        except asyncio.CancelledError:
            logger.info("feature-pipeline: cancelled, shutting down")
            return
        except Exception as exc:
            logger.error("feature-pipeline: unexpected error: %s", exc, exc_info=True)

        await asyncio.sleep(_PIPELINE_INTERVAL_SECONDS)
