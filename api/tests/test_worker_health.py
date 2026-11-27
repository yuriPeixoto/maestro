"""
The worker and the ingest process write their task reports to Postgres; the API's /health reads
them. A process that stopped, or whose event loop is blocked, must turn /health into a 503.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import heartbeats, worker_health
from app.config import settings
from app.health import router as health_router
from app.task_health import STATE_DOWN, STATE_OK, TaskRegistry
from app.worker_health import INGEST_PROCESS, WORKER_PROCESS, ProcessReport

_NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _registry(beat: bool = True, task: str = "metrics-consumer") -> TaskRegistry:
    registry = TaskRegistry(_Clock())
    registry.register(task, stale_after_seconds=60)
    registry.mark_running(task)
    if beat:
        registry.beat(task)
    return registry


def _report(registry: TaskRegistry, published_at: datetime = _NOW) -> ProcessReport:
    return ProcessReport(published_at, [asdict(r) for r in registry.reports()])


class TestDecodeReports:
    def test_fresh_report_lists_the_process_then_its_tasks(self):
        reports = worker_health.decode_reports(
            {WORKER_PROCESS: _report(_registry())}, [WORKER_PROCESS], now=_NOW + timedelta(seconds=5),
        )

        assert [(r.name, r.state) for r in reports] == [("worker", STATE_OK), ("metrics-consumer", STATE_OK)]
        assert reports[0].seconds_since_beat == 5.0

    def test_missing_report_means_the_process_is_down(self):
        reports = worker_health.decode_reports({}, [WORKER_PROCESS], now=_NOW)

        assert [(r.name, r.state, r.watched) for r in reports] == [("worker", STATE_DOWN, True)]

    def test_old_report_means_the_process_is_down_and_hides_its_tasks(self):
        late = _NOW + timedelta(seconds=worker_health.STALE_AFTER_SECONDS + 1)

        reports = worker_health.decode_reports({WORKER_PROCESS: _report(_registry())}, [WORKER_PROCESS], now=late)

        assert [(r.name, r.state) for r in reports] == [("worker", STATE_DOWN)]

    def test_unreadable_report_counts_as_down(self):
        broken = ProcessReport(_NOW, [{"name": "x"}])

        assert worker_health.decode_reports({WORKER_PROCESS: broken}, [WORKER_PROCESS], now=_NOW)[0].state == STATE_DOWN

    def test_each_expected_process_is_reported_and_a_missing_one_is_down(self):
        reports = worker_health.decode_reports(
            {WORKER_PROCESS: _report(_registry())}, [WORKER_PROCESS, INGEST_PROCESS], now=_NOW,
        )

        assert [(r.name, r.state) for r in reports] == [
            ("worker", STATE_OK), ("metrics-consumer", STATE_OK), ("ingest", STATE_DOWN),
        ]

    def test_a_report_of_a_process_this_installation_does_not_run_is_ignored(self):
        reports = worker_health.decode_reports(
            {WORKER_PROCESS: _report(_registry()), INGEST_PROCESS: _report(_registry())}, [WORKER_PROCESS], now=_NOW,
        )

        assert [r.name for r in reports] == ["worker", "metrics-consumer"]


@pytest.mark.parametrize(
    ("transport", "expected"),
    [("redis", ["worker"]), ("both", ["worker", "ingest"]), ("nats", ["worker", "ingest"])],
)
def test_the_ingest_process_is_expected_when_the_agents_use_nats(monkeypatch, transport, expected):
    monkeypatch.setattr(settings, "transport", transport)

    assert worker_health.expected_processes() == expected


class TestPublish:
    @pytest.mark.asyncio
    async def test_publish_replaces_the_process_row_and_withdraw_removes_it(self, postgres):
        await worker_health.publish(WORKER_PROCESS, _registry(beat=False), _NOW)
        await worker_health.publish(WORKER_PROCESS, _registry(), _NOW + timedelta(seconds=15))

        reports = await worker_health.read_reports([WORKER_PROCESS, INGEST_PROCESS])

        assert list(reports) == [WORKER_PROCESS]
        assert reports[WORKER_PROCESS].published_at == _NOW + timedelta(seconds=15)
        assert reports[WORKER_PROCESS].tasks[0]["seconds_since_beat"] == 0.0

        await worker_health.withdraw(WORKER_PROCESS)
        assert await worker_health.read_reports([WORKER_PROCESS]) == {}

    @pytest.mark.asyncio
    async def test_keeps_publishing_after_a_failure(self, monkeypatch):
        calls = 0

        async def flaky(name, registry, now):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ConnectionError("blip")
            raise asyncio.CancelledError

        async def no_sleep(_seconds: float) -> None:
            return None

        monkeypatch.setattr(worker_health, "publish", flaky)
        monkeypatch.setattr(worker_health.asyncio, "sleep", no_sleep)

        with pytest.raises(asyncio.CancelledError):
            await worker_health.publish_forever(WORKER_PROCESS, _registry(), clock=lambda: _NOW)

        assert calls == 2


class _Redis:
    def __init__(self, up: bool = True) -> None:
        self.up = up

    async def ping(self) -> bool:
        if not self.up:
            raise ConnectionError("redis down")
        return True


class _ClickHouse:
    async def query(self, _sql: str) -> None:
        return None


class _Nats:
    def __init__(self, up: bool) -> None:
        self.up = up

    async def ping(self) -> None:
        if not self.up:
            raise ConnectionError("nats down")


def _client(redis: _Redis | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(health_router)
    app.state.vuln_redis = redis or _Redis()
    app.state.ch_client = _ClickHouse()
    app.state.started_at = 0.0
    return TestClient(app)


async def _publish(name: str, registry: TaskRegistry) -> None:
    await worker_health.publish(name, registry, datetime.now(timezone.utc))


class TestHealthRoute:
    @pytest.mark.asyncio
    async def test_healthy_when_worker_tasks_and_dependencies_are_fine(self, postgres):
        await _publish(WORKER_PROCESS, _registry())

        resp = _client().get("/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["dependencies"] == {"redis": "ok", "clickhouse": "ok", "postgres": "ok"}
        assert [t["name"] for t in body["tasks"]] == ["worker", "metrics-consumer"]

    @pytest.mark.asyncio
    async def test_503_when_the_worker_published_nothing(self, postgres):
        resp = _client().get("/health")

        assert resp.status_code == 503
        assert resp.json()["tasks"] == [
            {"name": "worker", "state": STATE_DOWN, "watched": True, "restarts": 0, "seconds_since_beat": None},
        ]

    @pytest.mark.asyncio
    async def test_503_when_a_watched_worker_task_is_down(self, postgres):
        registry = _registry()
        registry.mark_stopped("metrics-consumer", restarting=True)
        await _publish(WORKER_PROCESS, registry)

        resp = _client().get("/health")

        assert resp.status_code == 503
        assert resp.json()["tasks"][1]["state"] == STATE_DOWN

    @pytest.mark.asyncio
    async def test_503_when_a_dependency_is_down(self, postgres):
        await _publish(WORKER_PROCESS, _registry())

        resp = _client(_Redis(up=False)).get("/health")

        assert resp.status_code == 503
        assert resp.json()["dependencies"]["redis"] == "down"

    @pytest.mark.asyncio
    async def test_with_nats_the_ingest_process_and_nats_are_checked(self, postgres, monkeypatch):
        monkeypatch.setattr(settings, "transport", "nats")
        heartbeats.use_source(_Nats(up=False))
        monkeypatch.setattr(heartbeats, "NatsHeartbeats", _Nats)
        await _publish(WORKER_PROCESS, _registry())
        await _publish(INGEST_PROCESS, _registry(task="maestro-ingest-metrics"))
        try:
            resp = _client().get("/health")
        finally:
            heartbeats.use_source(None)

        assert resp.status_code == 503
        body = resp.json()
        assert body["dependencies"]["nats"] == "down"
        assert [t["name"] for t in body["tasks"]] == ["worker", "metrics-consumer", "ingest", "maestro-ingest-metrics"]
