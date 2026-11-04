"""
The worker publishes its task reports to Redis; the API's /health reads them.
A worker that stopped, or whose event loop is blocked, must turn /health into a 503.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import worker_health
from app.config import settings
from app.health import router as health_router
from app.task_health import STATE_DOWN, STATE_OK, TaskRegistry


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _registry(beat: bool = True) -> TaskRegistry:
    registry = TaskRegistry(_Clock())
    registry.register("metrics-consumer", stale_after_seconds=60)
    registry.mark_running("metrics-consumer")
    if beat:
        registry.beat("metrics-consumer")
    return registry


class _Redis:
    def __init__(self, up: bool = True, report: str | None = None) -> None:
        self.up = up
        self.values: dict[str, str] = {}
        if report is not None:
            self.values[settings.worker_health_key] = report

    async def ping(self) -> bool:
        if not self.up:
            raise ConnectionError("redis down")
        return True

    async def get(self, key: str) -> str | None:
        if not self.up:
            raise ConnectionError("redis down")
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value


class _ClickHouse:
    async def query(self, _sql: str) -> None:
        return None


def _client(redis: _Redis) -> TestClient:
    app = FastAPI()
    app.include_router(health_router)
    app.state.vuln_redis = redis
    app.state.ch_client = _ClickHouse()
    app.state.started_at = 0.0
    return TestClient(app)


def _fresh_report(registry: TaskRegistry) -> str:
    return worker_health.encode_report(registry, time.time())


class TestDecodeReports:
    def test_fresh_report_lists_the_worker_then_its_tasks(self):
        reports = worker_health.decode_reports(worker_health.encode_report(_registry(), 100.0), now=105.0)

        assert [(r.name, r.state) for r in reports] == [("worker", STATE_OK), ("metrics-consumer", STATE_OK)]
        assert reports[0].seconds_since_beat == 5.0

    def test_missing_report_means_the_worker_is_down(self):
        reports = worker_health.decode_reports(None, now=100.0)

        assert [(r.name, r.state, r.watched) for r in reports] == [("worker", STATE_DOWN, True)]

    def test_old_report_means_the_worker_is_down_and_hides_its_tasks(self):
        raw = worker_health.encode_report(_registry(), 100.0)

        reports = worker_health.decode_reports(raw, now=100.0 + worker_health.STALE_AFTER_SECONDS + 1)

        assert [(r.name, r.state) for r in reports] == [("worker", STATE_DOWN)]

    def test_unreadable_report_counts_as_missing(self):
        assert worker_health.decode_reports("not json", now=100.0)[0].state == STATE_DOWN


class TestPublish:
    @pytest.mark.asyncio
    async def test_publishes_with_an_expiry_and_keeps_going_after_a_failure(self, monkeypatch):
        calls = 0

        class _FlakyRedis(_Redis):
            async def set(self, key, value, ex=None):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise ConnectionError("blip")
                self.values[key] = value
                self.ex = ex
                raise asyncio.CancelledError

        async def _no_sleep(_seconds: float) -> None:
            return None

        monkeypatch.setattr(worker_health.asyncio, "sleep", _no_sleep)
        redis = _FlakyRedis()

        with pytest.raises(asyncio.CancelledError):
            await worker_health.publish_forever(_registry(), redis, "key", clock=lambda: 100.0)

        assert calls == 2
        assert redis.ex > worker_health.STALE_AFTER_SECONDS
        assert worker_health.decode_reports(redis.values["key"], now=100.0)[0].state == STATE_OK


class TestHealthRoute:
    def test_healthy_when_worker_tasks_and_dependencies_are_fine(self):
        resp = _client(_Redis(report=_fresh_report(_registry()))).get("/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["dependencies"] == {"redis": "ok", "clickhouse": "ok"}
        assert [t["name"] for t in body["tasks"]] == ["worker", "metrics-consumer"]

    def test_503_when_the_worker_published_nothing(self):
        resp = _client(_Redis()).get("/health")

        assert resp.status_code == 503
        assert resp.json()["tasks"] == [
            {"name": "worker", "state": STATE_DOWN, "watched": True, "restarts": 0, "seconds_since_beat": None},
        ]

    def test_503_when_a_watched_worker_task_is_down(self):
        registry = _registry()
        registry.mark_stopped("metrics-consumer", restarting=True)

        resp = _client(_Redis(report=_fresh_report(registry))).get("/health")

        assert resp.status_code == 503
        assert resp.json()["tasks"][1]["state"] == STATE_DOWN

    def test_503_when_a_dependency_is_down(self):
        resp = _client(_Redis(up=False)).get("/health")

        assert resp.status_code == 503
        assert resp.json()["dependencies"]["redis"] == "down"
