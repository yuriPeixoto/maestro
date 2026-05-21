"""
River online ML integration — issue #25.

Runs HalfSpaceTrees (streaming anomaly detector) alongside Isolation Forest.
River updates its model incrementally with each new data point — no batch retraining.

Feature vector used (simpler than IF — no rolling stats needed, River learns them online):
  value, hour_sin, hour_cos, day_of_week, is_weekend

Background task polls for new metric data every 60 seconds, scores each point,
updates the model, and persists scores to anomaly_scores with model_version='river'.
River model state is saved to disk after every 500 updates.
"""
from __future__ import annotations

import asyncio
import logging
import math
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECONDS = 60
_SAVE_EVERY_N_UPDATES = 500
_WATERMARK_KEY = "maestro:river_watermarks"
_MODEL_VERSION = "river"


def _time_features(ts: datetime) -> dict[str, float]:
    hour_frac = ts.hour + ts.minute / 60 + ts.second / 3600
    radians = 2 * math.pi * hour_frac / 24
    return {
        "hour_sin": math.sin(radians),
        "hour_cos": math.cos(radians),
        "day_of_week": float(ts.weekday()),
        "is_weekend": 1.0 if ts.weekday() >= 5 else 0.0,
    }


class RiverDetector:
    """Per-(server, metric) HalfSpaceTrees online anomaly detector."""

    def __init__(self, models_dir: Path) -> None:
        self._dir = models_dir / "river"
        self._models: dict[tuple[str, str], object] = {}
        self._update_counts: dict[tuple[str, str], int] = {}

    def _model_path(self, server_id: str, metric_name: str) -> Path:
        return self._dir / server_id / f"{metric_name}.river.pkl"

    def load_all(self) -> int:
        if not self._dir.exists():
            return 0
        count = 0
        for pkl in self._dir.glob("*/*.river.pkl"):
            try:
                self._models[pkl.parent.name, pkl.stem.replace(".river", "")] = (
                    pickle.loads(pkl.read_bytes())
                )
                count += 1
            except Exception as exc:
                logger.warning("river: failed to load %s: %s", pkl, exc)
        logger.info("river: loaded %d model(s)", count)
        return count

    def _get_or_create(self, server_id: str, metric_name: str):
        key = (server_id, metric_name)
        if key not in self._models:
            from river import anomaly
            self._models[key] = anomaly.HalfSpaceTrees(seed=42)
            self._update_counts[key] = 0
        return self._models[key]

    def update_and_score(self, server_id: str, metric_name: str, value: float, ts: datetime) -> float:
        """Score one point then learn from it. Returns normalised score in [0, 1]."""
        model = self._get_or_create(server_id, metric_name)
        features = {"value": value, **_time_features(ts)}
        raw_score = model.score_one(features)
        model.learn_one(features)
        key = (server_id, metric_name)
        self._update_counts[key] = self._update_counts.get(key, 0) + 1
        return float(min(1.0, max(0.0, raw_score)))

    def save_if_due(self, server_id: str, metric_name: str) -> None:
        key = (server_id, metric_name)
        if self._update_counts.get(key, 0) % _SAVE_EVERY_N_UPDATES == 0:
            self._persist(server_id, metric_name)

    def _persist(self, server_id: str, metric_name: str) -> None:
        key = (server_id, metric_name)
        model = self._models.get(key)
        if model is None:
            return
        path = self._model_path(server_id, metric_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_bytes(pickle.dumps(model))
        except Exception as exc:
            logger.warning("river: failed to save %s/%s: %s", server_id, metric_name, exc)

    def save_all(self) -> None:
        for server_id, metric_name in list(self._models):
            self._persist(server_id, metric_name)


async def run_river_detector(reader, writer, detector: RiverDetector) -> None:
    """
    Background task: poll for new metric data every 60s, score with River,
    persist scores to anomaly_scores with model_version='river'.
    """
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    logger.info("river-detector: starting")
    try:
        while True:
            try:
                servers = await reader.get_known_server_ids()
                for server_id in servers:
                    metrics = await reader.get_metric_names(server_id)
                    for metric_name in metrics:
                        await _process_metric(reader, writer, redis, detector, server_id, metric_name)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("river-detector: error: %s", exc, exc_info=True)
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        detector.save_all()
        logger.info("river-detector: saved models, shutting down")
    finally:
        await redis.aclose()


async def _process_metric(reader, writer, redis, detector: RiverDetector,
                           server_id: str, metric_name: str) -> None:
    wm_key = f"{server_id}:{metric_name}"
    watermark_str = await redis.hget(_WATERMARK_KEY, wm_key)

    since = (
        datetime.fromisoformat(watermark_str)
        if watermark_str
        else datetime.now(tz=timezone.utc) - timedelta(hours=1)
    )

    rows = await reader.get_metrics_range(server_id, metric_name, since)
    if not rows:
        return

    timestamps, scores = [], []
    latest_ts = since
    for ts, value in rows:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        score = detector.update_and_score(server_id, metric_name, value, ts)
        timestamps.append(ts)
        scores.append(score)
        if ts > latest_ts:
            latest_ts = ts

    await writer.insert_anomaly_scores(server_id, metric_name, timestamps, scores, _MODEL_VERSION)
    detector.save_if_due(server_id, metric_name)

    if latest_ts > since:
        await redis.hset(_WATERMARK_KEY, wm_key, latest_ts.isoformat())
