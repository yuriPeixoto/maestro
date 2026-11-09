from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app import alert_store, server_store
from app.auth import require_active_user
from app.clickhouse import ClickHouseReader
from app.config import settings
from app.health_status import (
    MetricLimits,
    Readings,
    cpu_limits,
    disk_limits,
    health_headline,
    health_state,
    installed_services,
    memory_limits,
)
from app.server_store import ServerNames

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/servers", tags=["servers"])


class ServerStatus(BaseModel):
    server_id: str           # the hostname: the identity everywhere shared
    status: str
    last_seen: str | None
    agent_version: str | None
    label: str | None = None       # shared name, set by an admin
    group_id: int | None = None
    group_name: str | None = None
    nickname: str | None = None    # the caller's own name for it; screens show it first


async def get_redis() -> aioredis.Redis:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
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


def _with_names(status: ServerStatus, names: ServerNames | None) -> ServerStatus:
    if names is None:
        return status
    return status.model_copy(update={
        "label": names.label, "group_id": names.group_id, "group_name": names.group_name, "nickname": names.nickname,
    })


@router.get("", response_model=list[ServerStatus])
async def list_servers(redis: aioredis.Redis = Depends(get_redis), user: dict = Depends(require_active_user)):
    all_entries: dict[str, str] = await redis.hgetall(settings.heartbeat_state_key)
    names = await server_store.server_names(user["id"], list(all_entries))
    return [_with_names(_build_server_status(sid, raw), names.get(sid)) for sid, raw in all_entries.items()]


@router.get("/{server_id}/status", response_model=ServerStatus)
async def get_server_status(
    server_id: str, redis: aioredis.Redis = Depends(get_redis), user: dict = Depends(require_active_user),
):
    raw: str | None = await redis.hget(settings.heartbeat_state_key, server_id)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")
    names = await server_store.server_names(user["id"], [server_id])
    return _with_names(_build_server_status(server_id, raw), names.get(server_id))


# ── Health snapshot ───────────────────────────────────────────────────────────

class MetricHealth(BaseModel):
    value: float | None
    baseline: float | None
    threshold: float         # critical limit
    attention: float         # attention limit
    trend: str               # "up" | "down" | "stable"
    spark: list[float]
    projection_hours: int | None  # hours to the critical limit — only for memory trending up


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
    open_alerts: int
    critical_services: list[CriticalService]
    headline_code: str
    headline_params: dict[str, float]


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


def _projection_hours(current: float | None, spark: list[float], threshold: float) -> int | None:
    if current is None or len(spark) < 5:
        return None
    rate_per_hour = spark[-1] - spark[0]
    if rate_per_hour < 0.5:
        return None
    hours = (threshold - current) / rate_per_hour
    if 0 < hours < 24:
        return round(hours)
    return None


def _metric_health(
    value: float | None,
    baseline: float | None,
    limits: MetricLimits,
    spark: list[float],
    projection_hours: int | None = None,
) -> MetricHealth:
    return MetricHealth(
        value=value, baseline=baseline, threshold=limits.critical, attention=limits.attention,
        trend=_trend(spark), spark=spark, projection_hours=projection_hours,
    )


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
        anomalies6h, open_alerts,
    ) = await asyncio.gather(
        reader.get_status_metric_value(server_id, "cpu_usage_percent"),
        reader.get_status_metric_value(server_id, "memory_usage_percent"),
        reader.get_status_metric_value(server_id, "disk_usage_percent"),
        reader.get_metric_baseline_7d(server_id, "cpu_usage_percent"),
        reader.get_metric_baseline_7d(server_id, "memory_usage_percent"),
        reader.get_metric_baseline_7d(server_id, "disk_usage_percent"),
        reader.get_metric_sparkline(server_id, "cpu_usage_percent"),
        reader.get_metric_sparkline(server_id, "memory_usage_percent"),
        reader.get_metric_sparkline(server_id, "disk_usage_percent"),
        reader.get_anomaly_count_6h(server_id),
        alert_store.firing_severities(server_id),
    )
    open_severities = list(open_alerts.values())

    raw = await redis.hget(settings.heartbeat_state_key, server_id)
    server_status = _build_server_status(server_id, raw).status
    inventory = json.loads(raw).get("inventory") or [] if raw else []

    readings = Readings(cpu=cpu_val, memory=mem_val, disk=disk_val)
    memory = memory_limits()
    mem_proj = _projection_hours(mem_val, mem_spark, memory.critical)
    memory_rising = _trend(mem_spark) == "up" and mem_proj is not None
    state = health_state(server_status, readings, memory_rising, open_severities)
    headline = health_headline(
        server_status, readings, cpu_base,
        mem_proj if memory_rising else None, len(open_severities),
    )

    return ServerHealthSnapshot(
        server_id=server_id,
        state=state,
        cpu=_metric_health(cpu_val, cpu_base, cpu_limits(), cpu_spark),
        memory=_metric_health(mem_val, mem_base, memory, mem_spark, mem_proj),
        disk=_metric_health(disk_val, disk_base, disk_limits(), disk_spark),
        anomalies6h=anomalies6h,
        open_alerts=len(open_severities),
        critical_services=[CriticalService(**svc) for svc in installed_services(inventory)],
        headline_code=headline.code,
        headline_params=headline.params,
    )
