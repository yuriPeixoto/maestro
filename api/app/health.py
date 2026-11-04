"""`/health`: whether Maestro is doing its job, not only whether the API answers.

The API itself runs no background task; the worker does, and publishes how its
tasks are doing to Redis (see worker_health). This endpoint combines that report
with the API's own dependencies.

It needs no login, because an outside watchdog polls it, so it lists task names
and states but never error messages, hosts or data.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app import worker_health
from app.config import settings
from app.task_health import STATE_OK, STATE_STARTING

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

_DEPENDENCY_TIMEOUT_SECONDS = 3.0
DEPENDENCY_OK = "ok"
DEPENDENCY_DOWN = "down"


class TaskOut(BaseModel):
    name: str
    state: str
    watched: bool
    restarts: int
    seconds_since_beat: float | None


class HealthOut(BaseModel):
    status: str
    checked_at: str
    uptime_seconds: int
    dependencies: dict[str, str]
    tasks: list[TaskOut]


async def _probe(name: str, check) -> str:
    try:
        await asyncio.wait_for(check(), timeout=_DEPENDENCY_TIMEOUT_SECONDS)
        return DEPENDENCY_OK
    except Exception as exc:
        logger.warning("health: %s check failed: %s", name, exc)
        return DEPENDENCY_DOWN


async def _worker_report(redis) -> str | None:
    try:
        return await asyncio.wait_for(redis.get(settings.worker_health_key), timeout=_DEPENDENCY_TIMEOUT_SECONDS)
    except Exception:
        return None  # Redis itself is reported as a dependency


@router.get("/health", response_model=HealthOut)
async def health(request: Request, response: Response) -> HealthOut:
    state = request.app.state
    redis_state, clickhouse_state, raw_report = await asyncio.gather(
        _probe("redis", state.vuln_redis.ping),
        _probe("clickhouse", lambda: state.ch_client.query("SELECT 1")),
        _worker_report(state.vuln_redis),
    )
    dependencies = {"redis": redis_state, "clickhouse": clickhouse_state}
    tasks = worker_health.decode_reports(raw_report, time.time())

    tasks_ok = all(t.state in (STATE_OK, STATE_STARTING) for t in tasks if t.watched)
    healthy = tasks_ok and all(v == DEPENDENCY_OK for v in dependencies.values())
    if not healthy:
        response.status_code = 503

    return HealthOut(
        status="healthy" if healthy else "unhealthy",
        checked_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        uptime_seconds=int(time.monotonic() - state.started_at),
        dependencies=dependencies,
        tasks=[TaskOut(**vars(report)) for report in tasks],
    )
