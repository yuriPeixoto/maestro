"""Capacity planning forecast endpoints — issue #27."""
from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import settings
from app.ml.forecaster import compute_runway

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/forecasts", tags=["forecasts"])

_FORECAST_METRICS = ["disk_usage_percent", "memory_usage_percent", "cpu_usage_percent"]

# For CPU the interesting threshold is headroom below 80% sustained, not "full".
# We report runway to 90% for all metrics for consistency; the frontend labels it.
_RUNWAY_THRESHOLD = 90.0
_WATCH_DAYS = 30
_CRITICAL_DAYS = 15


def _forecast_key(server_id: str, metric_name: str) -> str:
    return f"maestro:forecast:{server_id}:{metric_name}"


# ── Pydantic models ───────────────────────────────────────────────────────────

class ForecastPointOut(BaseModel):
    date: str
    yhat: float
    yhat_lower: float
    yhat_upper: float


class ForecastOut(BaseModel):
    server_id: str
    metric_name: str
    status: str
    horizon_days: int
    trained_at: str
    points: list[ForecastPointOut]


class RunwayMetricOut(BaseModel):
    metric_name: str
    days_to_threshold: int | None   # None = never reaches threshold in horizon
    current_value: float | None
    status: str                     # "safe" | "watch" | "critical" | "no_data"


class RunwayOut(BaseModel):
    server_id: str
    threshold_pct: float
    metrics: list[RunwayMetricOut]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_cached(redis: aioredis.Redis, key: str) -> dict | None:
    raw = await redis.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _runway_status(days: int | None) -> str:
    if days is None:
        return "safe"
    if days < _CRITICAL_DAYS:
        return "critical"
    if days < _WATCH_DAYS:
        return "watch"
    return "safe"


# ── Endpoints ─────────────────────────────────────────────────────────────────

class DailyPoint(BaseModel):
    date: str
    avg_value: float


@router.get("/{server_id}/{metric_name}/history", response_model=list[DailyPoint])
async def get_metric_history(
    server_id: str, metric_name: str, request: Request, days: int = 30
) -> list[DailyPoint]:
    """Return daily averages for the past N days — used to render the history portion of the forecast chart."""
    from app.clickhouse import ClickHouseReader
    reader: ClickHouseReader = request.app.state.ch_reader
    rows = await reader.get_daily_aggregates(server_id, metric_name, days=days)
    return [DailyPoint(**r) for r in rows]


@router.get("/{server_id}/{metric_name}", response_model=ForecastOut)
async def get_forecast(server_id: str, metric_name: str, request: Request) -> ForecastOut:
    """Return the latest cached forecast for a server/metric pair."""
    redis: aioredis.Redis = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
    try:
        data = await _get_cached(redis, _forecast_key(server_id, metric_name))
    finally:
        await redis.aclose()

    if data is None:
        raise HTTPException(
            status_code=404,
            detail="No forecast available yet. The scheduler trains on startup and every 24h.",
        )
    return ForecastOut(**data)


@router.get("/{server_id}/runway", response_model=RunwayOut)
async def get_runway(server_id: str, request: Request) -> RunwayOut:
    """Return days-to-threshold and status for all capacity metrics."""
    redis: aioredis.Redis = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
    try:
        results: list[RunwayMetricOut] = []
        for metric_name in _FORECAST_METRICS:
            data = await _get_cached(redis, _forecast_key(server_id, metric_name))
            if data is None or data.get("status") != "ok" or not data.get("points"):
                results.append(RunwayMetricOut(
                    metric_name=metric_name,
                    days_to_threshold=None,
                    current_value=None,
                    status="no_data",
                ))
                continue

            from app.ml.forecaster import ForecastPoint as FP
            points = [FP(**p) for p in data["points"]]
            days = compute_runway(points, threshold=_RUNWAY_THRESHOLD)
            current_value = data["points"][0]["yhat"] if data["points"] else None

            results.append(RunwayMetricOut(
                metric_name=metric_name,
                days_to_threshold=days,
                current_value=current_value,
                status=_runway_status(days),
            ))
    finally:
        await redis.aclose()

    return RunwayOut(server_id=server_id, threshold_pct=_RUNWAY_THRESHOLD, metrics=results)
