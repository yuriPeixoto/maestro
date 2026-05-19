"""
Isolation Forest anomaly detection — issue #22.

Background task that trains one IsolationForest model per (server_id, metric_name)
using pre-computed features from metric_features, persists the model via ModelStore,
and writes normalised anomaly scores to the anomaly_scores ClickHouse table.

Training cadence: every 24 hours.
Minimum samples: 500 data points (logs a warning and skips if below threshold).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from app.ml.model_store import ModelMetadata, ModelStore

logger = logging.getLogger(__name__)

_TRAINING_INTERVAL_SECONDS = 86_400   # 24 hours
_MIN_SAMPLES = 500                     # minimum rows in metric_features to train

FEATURE_COLUMNS = [
    "rolling_mean_5m",
    "rolling_std_5m",
    "rate_of_change",
    "hour_sin",
    "hour_cos",
    "day_of_week",
    "is_weekend",
]


def _get_contamination() -> float:
    try:
        c = float(os.getenv("MAESTRO_ML_CONTAMINATION", "0.05"))
        return max(0.01, min(c, 0.5))
    except ValueError:
        return 0.05


def train_model(
    features_df: pd.DataFrame,
    server_id: str,
    metric_name: str,
    contamination: float,
) -> tuple[IsolationForest, ModelMetadata]:
    """
    Train an IsolationForest on a feature DataFrame and return the fitted model
    together with its metadata (score normalisation bounds included).

    Pure function — no I/O, fully unit-testable.

    Args:
        features_df: DataFrame with at minimum the FEATURE_COLUMNS columns
                     plus a 'timestamp' column (tz-aware UTC).
        server_id:   Server identifier.
        metric_name: Metric name.
        contamination: Expected fraction of outliers in [0.01, 0.5].

    Returns:
        (fitted_model, ModelMetadata)
    """
    X = features_df[FEATURE_COLUMNS].values.astype(np.float64)

    model = IsolationForest(
        contamination=contamination,
        random_state=42,
        n_jobs=1,  # VPS has 1 vCPU — no benefit from parallelism
    )
    model.fit(X)

    # Compute score normalisation bounds from training set
    scores = model.decision_function(X)
    score_min = float(scores.min())
    score_max = float(scores.max())

    timestamps = pd.to_datetime(features_df["timestamp"], utc=True)
    now = datetime.now(tz=timezone.utc).isoformat()

    metadata = ModelMetadata(
        server_id=server_id,
        metric_name=metric_name,
        trained_at=now,
        data_range_start=timestamps.min().isoformat(),
        data_range_end=timestamps.max().isoformat(),
        n_samples=len(X),
        contamination=contamination,
        score_min=score_min,
        score_max=score_max,
        version=now,
    )

    return model, metadata


def score_dataframe(
    model: IsolationForest,
    metadata: ModelMetadata,
    features_df: pd.DataFrame,
) -> np.ndarray:
    """
    Score a feature DataFrame using a fitted model.

    Returns a numpy array of normalised scores in [0, 1] (1 = most anomalous),
    one value per row in features_df.
    """
    X = features_df[FEATURE_COLUMNS].values.astype(np.float64)
    raw = model.decision_function(X)
    score_range = metadata.score_max - metadata.score_min
    if score_range == 0.0:
        return np.full(len(X), 0.5)
    normalized = (metadata.score_max - raw) / score_range
    return np.clip(normalized, 0.0, 1.0)


async def _process_one(
    reader,
    writer,
    store: ModelStore,
    server_id: str,
    metric_name: str,
) -> bool:
    """Train, persist, and score one (server_id, metric_name). Returns True if trained."""
    features_df = await reader.get_features_for_training(server_id, metric_name)

    if features_df is None or len(features_df) < _MIN_SAMPLES:
        n = len(features_df) if features_df is not None else 0
        logger.debug(
            "anomaly-detector: %s/%s has %d samples (min=%d) — skipping",
            server_id, metric_name, n, _MIN_SAMPLES,
        )
        return False

    contamination = _get_contamination()

    try:
        model, metadata = train_model(features_df, server_id, metric_name, contamination)
        store.save(server_id, metric_name, model, metadata)
    except Exception as exc:
        logger.error("anomaly-detector: training failed for %s/%s: %s", server_id, metric_name, exc)
        return False

    # Score all training rows and persist to anomaly_scores
    scores = score_dataframe(model, metadata, features_df)
    timestamps = pd.to_datetime(features_df["timestamp"], utc=True).tolist()
    await writer.insert_anomaly_scores(
        server_id, metric_name, timestamps, scores.tolist(), metadata.version
    )

    logger.info(
        "anomaly-detector: trained %s/%s — n=%d contamination=%.2f",
        server_id, metric_name, metadata.n_samples, contamination,
    )
    return True


async def run_anomaly_detector(reader, writer, store: ModelStore) -> None:
    """
    Background task: train Isolation Forest models for all known servers/metrics,
    then repeat every 24 hours.
    """
    logger.info("anomaly-detector: starting")
    while True:
        try:
            servers = await reader.get_known_server_ids()
            trained = 0
            for server_id in servers:
                metrics = await reader.get_metric_names(server_id)
                for metric_name in metrics:
                    if await _process_one(reader, writer, store, server_id, metric_name):
                        trained += 1
            logger.info("anomaly-detector: cycle complete — %d model(s) trained/updated", trained)
        except asyncio.CancelledError:
            logger.info("anomaly-detector: cancelled, shutting down")
            return
        except Exception as exc:
            logger.error("anomaly-detector: unexpected error: %s", exc, exc_info=True)

        await asyncio.sleep(_TRAINING_INTERVAL_SECONDS)
