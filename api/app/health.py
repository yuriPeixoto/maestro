"""`/health`: whether this API is doing its job, not only whether it answers.

It needs no login, because an outside watchdog polls it, so it lists task
names and states but never error messages, hosts or data.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.task_health import TaskRegistry

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


@router.get("/health", response_model=HealthOut)
async def health(request: Request, response: Response) -> HealthOut:
    state = request.app.state
    registry: TaskRegistry = state.task_registry
    redis_state, clickhouse_state = await asyncio.gather(
        _probe("redis", state.vuln_redis.ping),
        _probe("clickhouse", lambda: state.ch_client.query("SELECT 1")),
    )
    dependencies = {"redis": redis_state, "clickhouse": clickhouse_state}
    healthy = registry.healthy() and all(v == DEPENDENCY_OK for v in dependencies.values())
    if not healthy:
        response.status_code = 503

    return HealthOut(
        status="healthy" if healthy else "unhealthy",
        checked_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        uptime_seconds=int(time.monotonic() - state.started_at),
        dependencies=dependencies,
        tasks=[TaskOut(**vars(report)) for report in registry.reports()],
    )
