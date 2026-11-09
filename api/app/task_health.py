"""Keep the background tasks running and say whether they are doing their job.

`supervise` restarts a task that crashed or returned. A watched task also calls
`beat` after every cycle that did its work, so a task that is alive but stuck
(ClickHouse refusing every insert, an evaluation that never finishes) reads as
stale instead of healthy.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_RESTART_BASE_DELAY_SECONDS = 1.0
_RESTART_MAX_DELAY_SECONDS = 60.0

STATE_OK = "ok"
STATE_STARTING = "starting"
STATE_STALE = "stale"
STATE_DOWN = "down"


@dataclass
class _Task:
    name: str
    stale_after_seconds: float | None
    started_at: float
    running: bool = False
    last_beat: float | None = None
    restarts: int = 0


@dataclass(frozen=True)
class TaskReport:
    name: str
    state: str
    watched: bool
    restarts: int
    seconds_since_beat: float | None


class TaskRegistry:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._tasks: dict[str, _Task] = {}

    def register(self, name: str, stale_after_seconds: float | None = None) -> None:
        """A task with `stale_after_seconds` must beat that often to count as healthy."""
        self._tasks[name] = _Task(name, stale_after_seconds, started_at=self._clock())

    def beat(self, name: str) -> None:
        self._tasks[name].last_beat = self._clock()

    def beater(self, name: str) -> Callable[[], None]:
        return lambda: self.beat(name)

    def mark_running(self, name: str) -> None:
        task = self._tasks[name]
        task.running = True
        task.started_at = self._clock()

    def mark_stopped(self, name: str, restarting: bool) -> float:
        """Return how long this run lasted, in seconds."""
        task = self._tasks[name]
        task.running = False
        if restarting:
            task.restarts += 1
        return self._clock() - task.started_at

    def reports(self) -> list[TaskReport]:
        now = self._clock()
        return [self._report(task, now) for task in self._tasks.values()]

    def healthy(self) -> bool:
        return all(r.state in (STATE_OK, STATE_STARTING) for r in self.reports() if r.watched)

    def _report(self, task: _Task, now: float) -> TaskReport:
        since_beat = None if task.last_beat is None else round(now - task.last_beat, 1)
        return TaskReport(
            name=task.name,
            state=self._state(task, now),
            watched=task.stale_after_seconds is not None,
            restarts=task.restarts,
            seconds_since_beat=since_beat,
        )

    @staticmethod
    def _state(task: _Task, now: float) -> str:
        if not task.running:
            return STATE_DOWN
        if task.stale_after_seconds is None:
            return STATE_OK
        if task.last_beat is not None and now - task.last_beat <= task.stale_after_seconds:
            return STATE_OK
        # No beat yet in this run: the first cycle gets the same grace as any other.
        if (task.last_beat is None or task.last_beat < task.started_at) and now - task.started_at <= task.stale_after_seconds:
            return STATE_STARTING
        return STATE_STALE


async def supervise(
    registry: TaskRegistry,
    name: str,
    run: Callable[[], Awaitable[None]],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Run `run` forever, restarting it with a growing pause when it stops."""
    delay = _RESTART_BASE_DELAY_SECONDS
    while True:
        registry.mark_running(name)
        try:
            await run()
        except asyncio.CancelledError:
            registry.mark_stopped(name, restarting=False)
            raise
        except Exception:
            logger.exception("task %s crashed — restarting in %.0fs", name, delay)
        else:
            # A task that swallowed our cancellation is shutting down, not failing:
            # no error, and no restart.
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                registry.mark_stopped(name, restarting=False)
                return
            logger.error("task %s returned on its own — restarting in %.0fs", name, delay)

        ran_for = registry.mark_stopped(name, restarting=True)
        if ran_for > _RESTART_MAX_DELAY_SECONDS:
            delay = _RESTART_BASE_DELAY_SECONDS
        await sleep(delay)
        delay = min(delay * 2, _RESTART_MAX_DELAY_SECONDS)
