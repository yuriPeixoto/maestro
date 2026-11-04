"""Background forecast scheduler — issue #27.

Retrains one Prophet model per (server_id, metric_name) combination and caches
the result in Redis. Runs immediately on startup, then every 24 hours.

Prophet.fit() is CPU-intensive and synchronous, so each training call runs in
the ML child process (app.ml.pool) instead of the worker's event loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.clickhouse import ClickHouseReader
from app.config import settings
from app.ml.forecaster import (
    FORECAST_HORIZON_DAYS,
    TRAINING_WINDOW_DAYS,
    ForecastPoint,
    ForecastResult,
    forecast,
)
from app.ml.pool import run_in_ml_process

logger = logging.getLogger(__name__)

_RETRAIN_INTERVAL = 86_400  # 24 hours
_FORECAST_TTL = 90_000      # 25 hours — survives one missed cycle

# Metrics we forecast for capacity planning
_FORECAST_METRICS = [
    "disk_usage_percent",
    "memory_usage_percent",
    "cpu_usage_percent",
]


def _forecast_key(server_id: str, metric_name: str) -> str:
    return f"maestro:forecast:{server_id}:{metric_name}"


def _result_to_dict(result: ForecastResult) -> dict:
    return {
        "server_id": result.server_id,
        "metric_name": result.metric_name,
        "status": result.status,
        "horizon_days": result.horizon_days,
        "trained_at": result.trained_at,
        "points": [
            {"date": p.date, "yhat": p.yhat, "yhat_lower": p.yhat_lower, "yhat_upper": p.yhat_upper}
            for p in result.points
        ],
    }


async def _train_one(
    reader: ClickHouseReader,
    redis: aioredis.Redis,
    server_id: str,
    metric_name: str,
) -> None:
    daily_data = await reader.get_daily_aggregates(server_id, metric_name, days=TRAINING_WINDOW_DAYS)
    trained_at = datetime.now(timezone.utc).isoformat()

    result: ForecastResult = await run_in_ml_process(
        forecast,
        server_id=server_id,
        metric_name=metric_name,
        daily_data=daily_data,
        horizon_days=FORECAST_HORIZON_DAYS,
        trained_at=trained_at,
    )

    key = _forecast_key(server_id, metric_name)
    await redis.set(key, json.dumps(_result_to_dict(result)), ex=_FORECAST_TTL)

    if result.status == "ok":
        logger.info(
            "forecast_scheduler: trained %s/%s — %d points cached",
            server_id, metric_name, len(result.points),
        )
    else:
        logger.warning(
            "forecast_scheduler: %s/%s status=%s",
            server_id, metric_name, result.status,
        )


async def _retrain_all(reader: ClickHouseReader, redis: aioredis.Redis) -> None:
    server_ids: list[str] = await redis.hkeys(settings.heartbeat_state_key)
    if not server_ids:
        logger.debug("forecast_scheduler: no servers in heartbeat — skipping cycle")
        return

    for server_id in server_ids:
        for metric_name in _FORECAST_METRICS:
            try:
                await _train_one(reader, redis, server_id, metric_name)
            except Exception as exc:
                logger.error(
                    "forecast_scheduler: failed %s/%s: %s", server_id, metric_name, exc
                )


async def run_forecast_scheduler(reader: ClickHouseReader) -> None:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
    try:
        logger.info("forecast_scheduler: started (interval=%ds)", _RETRAIN_INTERVAL)
        # First run — train immediately so the API is populated on startup
        await _retrain_all(reader, redis)
        while True:
            await asyncio.sleep(_RETRAIN_INTERVAL)
            await _retrain_all(reader, redis)
    except asyncio.CancelledError:
        logger.info("forecast_scheduler: shutting down")
    finally:
        await redis.aclose()
