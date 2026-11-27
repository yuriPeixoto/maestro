"""How each Maestro process's tasks are doing, passed to the API through Postgres (ADR-015).

The worker and the ingest process each write their task reports to `process_health` every few
seconds. The API's /health reads them: a process whose report is missing or too old is down or
stuck, and /health answers 503 just as it does for a stalled task. Postgres rather than NATS,
because /health already depends on it and a NATS outage must not read as a dead worker.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app import db
from app.config import settings
from app.models import ProcessHealthRow
from app.task_health import STATE_DOWN, STATE_OK, TaskRegistry, TaskReport

logger = logging.getLogger(__name__)

PUBLISH_INTERVAL_SECONDS = 15.0
# Three missed publications: the process is gone or its event loop is blocked.
STALE_AFTER_SECONDS = PUBLISH_INTERVAL_SECONDS * 3

WORKER_PROCESS = "worker"
INGEST_PROCESS = "ingest"


def expected_processes() -> list[str]:
    """The processes this installation runs, from MAESTRO_TRANSPORT: the ingest process reads NATS."""
    if settings.transport == "redis":
        return [WORKER_PROCESS]
    return [WORKER_PROCESS, INGEST_PROCESS]


@dataclass(frozen=True)
class ProcessReport:
    published_at: datetime
    tasks: list[dict]


def decode_reports(reports: dict[str, ProcessReport], expected: list[str], now: datetime) -> list[TaskReport]:
    """For each expected process, a report for the process itself followed by its tasks.

    Without a fresh report the process counts as down and its tasks are not listed: their last
    known states could hide that nothing is running.
    """
    decoded: list[TaskReport] = []
    for name in expected:
        report = reports.get(name)
        if report is None:
            decoded.append(_process_report(name, STATE_DOWN, seconds_since_beat=None))
            continue
        age = round((now - report.published_at).total_seconds(), 1)
        if age > STALE_AFTER_SECONDS:
            decoded.append(_process_report(name, STATE_DOWN, seconds_since_beat=age))
            continue
        try:
            tasks = [TaskReport(**task) for task in report.tasks]
        except TypeError:
            logger.warning("process-health: unreadable report of %s", name)
            decoded.append(_process_report(name, STATE_DOWN, seconds_since_beat=age))
            continue
        decoded.append(_process_report(name, STATE_OK, seconds_since_beat=max(age, 0.0)))
        decoded.extend(tasks)
    return decoded


def _process_report(name: str, state: str, seconds_since_beat: float | None) -> TaskReport:
    return TaskReport(name=name, state=state, watched=True, restarts=0, seconds_since_beat=seconds_since_beat)


async def read_reports(names: list[str]) -> dict[str, ProcessReport]:
    statement = select(ProcessHealthRow).where(ProcessHealthRow.name.in_(names))
    async with db.session() as session:
        rows = (await session.scalars(statement)).all()
    return {row.name: ProcessReport(row.published_at, list(row.tasks)) for row in rows}


async def publish(name: str, registry: TaskRegistry, now: datetime) -> None:
    tasks = [asdict(report) for report in registry.reports()]
    statement = insert(ProcessHealthRow).values(name=name, published_at=now, tasks=tasks)
    statement = statement.on_conflict_do_update(
        index_elements=[ProcessHealthRow.name],
        set_={"published_at": statement.excluded.published_at, "tasks": statement.excluded.tasks},
    )
    async with db.session() as session:
        await session.execute(statement)


async def withdraw(name: str) -> None:
    """Leave no report behind on a clean stop: the API should see the process gone at once."""
    with contextlib.suppress(Exception):
        async with db.session() as session:
            await session.execute(delete(ProcessHealthRow).where(ProcessHealthRow.name == name))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def publish_forever(
    name: str,
    registry: TaskRegistry,
    clock: Callable[[], datetime] = _utc_now,
) -> None:
    """Publish the registry's reports until cancelled. Wall-clock time, since the API compares it
    with its own clock."""
    while True:
        try:
            await publish(name, registry, clock())
        except Exception as exc:
            # The API will see the report age; keep trying instead of dying.
            logger.warning("process-health: could not publish the report of %s: %s", name, exc)
        await asyncio.sleep(PUBLISH_INTERVAL_SECONDS)
