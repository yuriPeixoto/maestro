"""How the worker's tasks are doing, passed to the API through Redis.

The worker publishes its task reports every few seconds with a short expiry. The
API's /health reads them: a report that is missing or too old means the worker is
down or stuck, and /health answers 503 just as it does for a stalled task.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict

from app.task_health import STATE_DOWN, STATE_OK, TaskRegistry, TaskReport

logger = logging.getLogger(__name__)

PUBLISH_INTERVAL_SECONDS = 15.0
# Three missed publications: the worker is gone or its event loop is blocked.
STALE_AFTER_SECONDS = PUBLISH_INTERVAL_SECONDS * 3
# Redis drops a report nobody refreshes, so a stopped worker reads as missing.
_KEY_TTL_SECONDS = int(STALE_AFTER_SECONDS * 2)

WORKER_TASK_NAME = "worker"


def encode_report(registry: TaskRegistry, now: float) -> str:
    return json.dumps({
        "published_at": now,
        "tasks": [asdict(report) for report in registry.reports()],
    })


def decode_reports(raw: str | None, now: float) -> list[TaskReport]:
    """The worker's task reports, led by one for the worker itself.

    Without a fresh report the worker counts as down and its tasks are not listed:
    their last known states could hide that nothing is running.
    """
    payload = _parse(raw)
    if payload is None:
        return [_worker_report(STATE_DOWN, seconds_since_beat=None)]
    age = round(now - payload["published_at"], 1)
    if age > STALE_AFTER_SECONDS:
        return [_worker_report(STATE_DOWN, seconds_since_beat=age)]
    tasks = [TaskReport(**task) for task in payload["tasks"]]
    return [_worker_report(STATE_OK, seconds_since_beat=age), *tasks]


def _parse(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        float(payload["published_at"])
        list(payload["tasks"])
        return payload
    except (ValueError, KeyError, TypeError):
        logger.warning("worker-health: unreadable report in Redis")
        return None


def _worker_report(state: str, seconds_since_beat: float | None) -> TaskReport:
    return TaskReport(
        name=WORKER_TASK_NAME, state=state, watched=True, restarts=0, seconds_since_beat=seconds_since_beat,
    )


async def publish_forever(
    registry: TaskRegistry,
    redis,
    key: str,
    clock: Callable[[], float] = time.time,
) -> None:
    """Publish the registry's reports until cancelled. Wall-clock time, since the API
    compares it with its own clock."""
    while True:
        try:
            await redis.set(key, encode_report(registry, clock()), ex=_KEY_TTL_SECONDS)
        except Exception as exc:
            # The API will see the report age; keep trying instead of dying.
            logger.warning("worker-health: could not publish the report: %s", exc)
        await asyncio.sleep(PUBLISH_INTERVAL_SECONDS)
