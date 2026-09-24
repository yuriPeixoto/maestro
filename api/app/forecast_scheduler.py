"""Background forecast scheduler — issue #27.

Retrains one Prophet model per (server_id, metric_name) combination and caches
the result in Redis. Runs immediately on startup, then every 24 hours.

Prophet.fit() is CPU-intensive and synchronous, so each training call is
dispatched to a thread-pool executor to avoid blocking the event loop.
"""
from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial

import redis.asyncio as aioredis

from app.clickhouse import ClickHouseReader
from app.config import settings
from app.ml.forecaster import ForecastPoint, ForecastResult, forecast

logger = logging.getLogger(__name__)

_RETRAIN_INTERVAL = 86_400  # 24 hours
_HORIZON_DAYS = 14
_FORECAST_TTL = 90_000      # 25 hours — survives one missed cycle

# Metrics we forecast for capacity planning
_FORECAST_METRICS = [
    "disk_usage_percent",
    "memory_usage_percent",
    "cpu_usage_percent",
]

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="prophet")


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
    loop: asyncio.AbstractEventLoop,
    server_id: str,
    metric_name: str,
) -> None:
    daily_data = await reader.get_daily_aggregates(server_id, metric_name, days=60)
    trained_at = datetime.now(timezone.utc).isoformat()

    fn = partial(
        forecast,
        server_id=server_id,
        metric_name=metric_name,
        daily_data=daily_data,
        horizon_days=_HORIZON_DAYS,
        trained_at=trained_at,
    )
    result: ForecastResult = await loop.run_in_executor(_executor, fn)

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
    loop = asyncio.get_event_loop()
    server_ids: list[str] = await redis.hkeys(settings.heartbeat_state_key)
    if not server_ids:
        logger.debug("forecast_scheduler: no servers in heartbeat — skipping cycle")
        return

    for server_id in server_ids:
        for metric_name in _FORECAST_METRICS:
            try:
                await _train_one(reader, redis, loop, server_id, metric_name)
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
        _executor.shutdown(wait=False)
        await redis.aclose()
