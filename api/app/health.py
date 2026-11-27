"""`/health`: whether Maestro is doing its job, not only whether the API answers.

The API itself runs no background task; the worker and the ingest process do, and write how their
tasks are doing to Postgres (see worker_health). This endpoint combines those reports with the
API's own dependencies.

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
from sqlalchemy import text

from app import db, heartbeats, worker_health
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


async def _postgres_ping() -> None:
    async with db.session() as session:
        await session.execute(text("SELECT 1"))


async def _process_reports(names: list[str]) -> dict[str, worker_health.ProcessReport]:
    try:
        return await asyncio.wait_for(worker_health.read_reports(names), timeout=_DEPENDENCY_TIMEOUT_SECONDS)
    except Exception:
        return {}  # Postgres itself is reported as a dependency


def _nats_probe() -> list[tuple[str, object]]:
    if settings.transport == "redis":
        return []
    return [("nats", heartbeats.ping_nats)]


@router.get("/health", response_model=HealthOut)
async def health(request: Request, response: Response) -> HealthOut:
    state = request.app.state
    expected = worker_health.expected_processes()
    probes = [
        ("redis", state.vuln_redis.ping),
        ("clickhouse", lambda: state.ch_client.query("SELECT 1")),
        ("postgres", _postgres_ping),
        *_nats_probe(),
    ]
    *states, reports = await asyncio.gather(
        *(_probe(name, check) for name, check in probes), _process_reports(expected),
    )
    dependencies = {name: result for (name, _), result in zip(probes, states)}
    tasks = worker_health.decode_reports(reports, expected, datetime.now(timezone.utc))

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
