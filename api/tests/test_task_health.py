"""
A dead or stuck background task must show in /health and come back on its own.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.health import router as health_router
from app.task_health import (
    STATE_DOWN,
    STATE_OK,
    STATE_STALE,
    STATE_STARTING,
    TaskRegistry,
    supervise,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _registry(stale_after: float | None = 60) -> tuple[TaskRegistry, _Clock]:
    clock = _Clock()
    registry = TaskRegistry(clock)
    registry.register("worker", stale_after_seconds=stale_after)
    registry.mark_running("worker")
    return registry, clock


def _state(registry: TaskRegistry) -> str:
    return registry.reports()[0].state


class TestTaskState:
    def test_running_task_without_a_beat_yet_is_starting(self):
        registry, _ = _registry()

        assert _state(registry) == STATE_STARTING
        assert registry.healthy()

    def test_task_that_beat_recently_is_ok(self):
        registry, clock = _registry()
        clock.now += 30
        registry.beat("worker")

        assert _state(registry) == STATE_OK

    def test_task_that_stopped_beating_is_stale(self):
        registry, clock = _registry()
        registry.beat("worker")
        clock.now += 61

        assert _state(registry) == STATE_STALE
        assert not registry.healthy()

    def test_task_that_never_beat_goes_stale_after_the_grace(self):
        registry, clock = _registry()
        clock.now += 61

        assert _state(registry) == STATE_STALE

    def test_stopped_task_is_down(self):
        registry, _ = _registry()
        registry.mark_stopped("worker", restarting=True)

        assert _state(registry) == STATE_DOWN
        assert registry.reports()[0].restarts == 1

    def test_unwatched_task_never_makes_the_api_unhealthy(self):
        registry, clock = _registry(stale_after=None)
        clock.now += 10_000

        assert _state(registry) == STATE_OK
        registry.mark_stopped("worker", restarting=True)
        assert registry.healthy()


async def _no_sleep(_seconds: float) -> None:
    await asyncio.sleep(0)


class TestSupervise:
    @pytest.mark.asyncio
    async def test_crashed_task_is_restarted(self):
        registry = TaskRegistry()
        registry.register("worker")
        runs = 0
        done = asyncio.Event()

        async def run() -> None:
            nonlocal runs
            runs += 1
            if runs < 3:
                raise RuntimeError("boom")
            done.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(supervise(registry, "worker", run, sleep=_no_sleep))
        await asyncio.wait_for(done.wait(), timeout=1)

        assert runs == 3
        assert registry.reports()[0].restarts == 2
        assert registry.reports()[0].state == STATE_OK
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_task_that_returns_is_restarted(self):
        registry = TaskRegistry()
        registry.register("worker")
        runs = 0
        done = asyncio.Event()

        async def run() -> None:
            nonlocal runs
            runs += 1
            if runs == 2:
                done.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(supervise(registry, "worker", run, sleep=_no_sleep))
        await asyncio.wait_for(done.wait(), timeout=1)

        assert runs == 2
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_task_that_swallows_cancellation_is_not_restarted(self):
        registry = TaskRegistry()
        registry.register("worker")
        runs = 0
        started = asyncio.Event()

        async def run() -> None:
            nonlocal runs
            runs += 1
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return

        task = asyncio.create_task(supervise(registry, "worker", run, sleep=_no_sleep))
        await started.wait()
        task.cancel()
        await asyncio.wait_for(task, timeout=1)

        assert runs == 1
        assert registry.reports()[0].state == STATE_DOWN


class _Redis:
    def __init__(self, up: bool) -> None:
        self.up = up

    async def ping(self) -> bool:
        if not self.up:
            raise ConnectionError("redis down")
        return True


class _ClickHouse:
    async def query(self, _sql: str) -> None:
        return None


def _client(registry: TaskRegistry, redis_up: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(health_router)
    app.state.task_registry = registry
    app.state.vuln_redis = _Redis(redis_up)
    app.state.ch_client = _ClickHouse()
    app.state.started_at = 0.0
    return TestClient(app)


class TestHealthRoute:
    def test_healthy_when_tasks_and_dependencies_are_fine(self):
        registry, _ = _registry()
        registry.beat("worker")

        resp = _client(registry).get("/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["dependencies"] == {"redis": "ok", "clickhouse": "ok"}
        assert body["tasks"][0]["name"] == "worker"

    def test_unhealthy_with_503_when_a_watched_task_is_down(self):
        registry, _ = _registry()
        registry.mark_stopped("worker", restarting=True)

        resp = _client(registry).get("/health")

        assert resp.status_code == 503
        assert resp.json()["status"] == "unhealthy"
        assert resp.json()["tasks"][0]["state"] == STATE_DOWN

    def test_unhealthy_when_a_dependency_is_down(self):
        registry, _ = _registry()
        registry.beat("worker")

        resp = _client(registry, redis_up=False).get("/health")

        assert resp.status_code == 503
        assert resp.json()["dependencies"]["redis"] == "down"
