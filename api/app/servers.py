from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.clickhouse import ClickHouseReader
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/servers", tags=["servers"])


class ServerStatus(BaseModel):
    server_id: str
    status: str
    last_seen: str | None
    agent_version: str | None


async def get_redis() -> aioredis.Redis:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield redis
    finally:
        await redis.aclose()


def _resolve_status(last_seen_iso: str | None) -> str:
    if last_seen_iso is None:
        return "unknown"
    try:
        last_seen = datetime.fromisoformat(last_seen_iso)
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last_seen).total_seconds()
        return "online" if elapsed <= settings.offline_threshold_seconds else "offline"
    except ValueError:
        return "unknown"


def _build_server_status(server_id: str, raw_json: str | None) -> ServerStatus:
    if raw_json is None:
        return ServerStatus(server_id=server_id, status="unknown", last_seen=None, agent_version=None)
    try:
        data = json.loads(raw_json)
        last_seen = data.get("last_seen")
        return ServerStatus(
            server_id=server_id,
            status=_resolve_status(last_seen),
            last_seen=last_seen,
            agent_version=data.get("agent_version"),
        )
    except (json.JSONDecodeError, KeyError):
        return ServerStatus(server_id=server_id, status="unknown", last_seen=None, agent_version=None)


@router.get("", response_model=list[ServerStatus])
async def list_servers(redis: aioredis.Redis = Depends(get_redis)):
    all_entries: dict[str, str] = await redis.hgetall(settings.heartbeat_state_key)
    return [_build_server_status(sid, raw) for sid, raw in all_entries.items()]


@router.get("/{server_id}/status", response_model=ServerStatus)
async def get_server_status(server_id: str, redis: aioredis.Redis = Depends(get_redis)):
    raw: str | None = await redis.hget(settings.heartbeat_state_key, server_id)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")
    return _build_server_status(server_id, raw)


# ── Health snapshot ───────────────────────────────────────────────────────────

class MetricHealth(BaseModel):
    value: float | None
    baseline: float | None
    threshold: float
    trend: str               # "up" | "down" | "stable"
    spark: list[float]
    projection: str | None   # e.g. "90% in ~2h" — only for memory trending up


class CriticalService(BaseModel):
    name: str
    ok: bool


class ServerHealthSnapshot(BaseModel):
    server_id: str
    state: str               # "ok" | "attention" | "critical" | "quiet"
    cpu: MetricHealth
    memory: MetricHealth
    disk: MetricHealth
    anomalies6h: int
    critical_services: list[CriticalService]
    headline: str


_THRESHOLDS = {
    "cpu_usage_percent":    80.0,
    "memory_usage_percent": 90.0,
    "disk_usage_percent":   95.0,
}


def _trend(spark: list[float]) -> str:
    if len(spark) < 4:
        return "stable"
    half = len(spark) // 2
    first = sum(spark[:half]) / half
    second = sum(spark[half:]) / (len(spark) - half)
    diff = (second - first) / max(first, 0.1)
    if diff > 0.03:
        return "up"
    if diff < -0.03:
        return "down"
    return "stable"


def _projection(current: float | None, spark: list[float], threshold: float) -> str | None:
    if current is None or len(spark) < 5:
        return None
    rate_per_hour = spark[-1] - spark[0]
    if rate_per_hour < 0.5:
        return None
    hours = (threshold - current) / rate_per_hour
    if 0 < hours < 24:
        return f"{threshold:.0f}% in ~{round(hours)}h"
    return None


def _health_state(
    cpu_val: float | None,
    mem_val: float | None,
    disk_val: float | None,
    mem_trend: str,
    mem_proj: str | None,
) -> str:
    if cpu_val is None and mem_val is None:
        return "critical"
    if (cpu_val and cpu_val >= 80) or (mem_val and mem_val >= 90) or (disk_val and disk_val >= 95):
        return "critical"
    if mem_trend == "up" and mem_proj:
        return "attention"
    if (cpu_val and cpu_val >= 68) or (mem_val and mem_val >= 76) or (disk_val and disk_val >= 80):
        return "attention"
    return "ok"


def _headline(
    state: str,
    cpu_val: float | None,
    cpu_base: float | None,
    mem_val: float | None,
    mem_trend: str,
    mem_proj: str | None,
    anomalies6h: int,
) -> str:
    if cpu_val is None:
        return "offline — no metric collection."
    if mem_trend == "up" and mem_proj:
        return f"memory rising — projected {mem_proj}"
    if state == "critical":
        if cpu_val and cpu_val >= 80:
            return f"CPU critical at {cpu_val:.0f}%."
        if mem_val and mem_val >= 90:
            return f"memory critical at {mem_val:.0f}%."
    if cpu_base and cpu_val and cpu_val > cpu_base * 1.10:
        delta = round(cpu_val - cpu_base)
        return f"CPU {delta}pp above average."
    if anomalies6h > 0:
        return f"{anomalies6h} anomal{'ies' if anomalies6h != 1 else 'y'} in the last 6h."
    return "all within expected range."


@router.get("/{server_id}/health-snapshot", response_model=ServerHealthSnapshot)
async def get_health_snapshot(
    server_id: str,
    request: Request,
    redis: aioredis.Redis = Depends(get_redis),
) -> ServerHealthSnapshot:
    reader: ClickHouseReader = request.app.state.ch_reader

    (
        cpu_val, mem_val, disk_val,
        cpu_base, mem_base, disk_base,
        cpu_spark, mem_spark, disk_spark,
        anomalies6h,
    ) = await asyncio.gather(
        reader.get_latest_metric_value(server_id, "cpu_usage_percent"),
        reader.get_latest_metric_value(server_id, "memory_usage_percent"),
        reader.get_latest_metric_value(server_id, "disk_usage_percent"),
        reader.get_metric_baseline_7d(server_id, "cpu_usage_percent"),
        reader.get_metric_baseline_7d(server_id, "memory_usage_percent"),
        reader.get_metric_baseline_7d(server_id, "disk_usage_percent"),
        reader.get_metric_sparkline(server_id, "cpu_usage_percent"),
        reader.get_metric_sparkline(server_id, "memory_usage_percent"),
        reader.get_metric_sparkline(server_id, "disk_usage_percent"),
        reader.get_anomaly_count_6h(server_id),
    )

    cpu_t  = _trend(cpu_spark)
    mem_t  = _trend(mem_spark)
    disk_t = _trend(disk_spark)
    mem_proj = _projection(mem_val, mem_spark, _THRESHOLDS["memory_usage_percent"])
    state = _health_state(cpu_val, mem_val, disk_val, mem_t, mem_proj)
    headline = _headline(state, cpu_val, cpu_base, mem_val, mem_t, mem_proj, anomalies6h)

    # Critical services from Redis heartbeat inventory
    raw = await redis.hget(settings.heartbeat_state_key, server_id)
    services: list[CriticalService] = []
    if raw:
        data = json.loads(raw)
        services = [
            CriticalService(name=e["name"], ok=e.get("status") == "active")
            for e in data.get("inventory") or []
        ]

    return ServerHealthSnapshot(
        server_id=server_id,
        state=state,
        cpu=MetricHealth(
            value=cpu_val, baseline=cpu_base, threshold=_THRESHOLDS["cpu_usage_percent"],
            trend=cpu_t, spark=cpu_spark, projection=None,
        ),
        memory=MetricHealth(
            value=mem_val, baseline=mem_base, threshold=_THRESHOLDS["memory_usage_percent"],
            trend=mem_t, spark=mem_spark, projection=mem_proj,
        ),
        disk=MetricHealth(
            value=disk_val, baseline=disk_base, threshold=_THRESHOLDS["disk_usage_percent"],
            trend=disk_t, spark=disk_spark, projection=None,
        ),
        anomalies6h=anomalies6h,
        critical_services=services,
        headline=headline,
    )