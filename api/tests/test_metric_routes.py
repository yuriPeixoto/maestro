"""
Metric series endpoint: raw samples up to a day, hourly rollup beyond it.

A minimal app mounts only the metrics router, with an in-memory reader that
records which source each request was answered from.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.clickhouse import DataPoint
from app.config import settings
from app.metrics import router as metrics_router

SERVER = "web-1"
METRIC = "cpu_usage_percent"
_POINT = DataPoint(timestamp=datetime(2026, 11, 3, 12, tzinfo=timezone.utc), value=42.0)


class _FakeReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def get_metric_series(self, server_id: str, metric_name: str, minutes: int) -> list[DataPoint]:
        self.calls.append(("raw", minutes))
        return [_POINT]

    async def get_metric_series_hourly(self, server_id: str, metric_name: str, minutes: int) -> list[DataPoint]:
        self.calls.append(("hourly", minutes))
        return [_POINT]


def _client() -> tuple[TestClient, _FakeReader]:
    app = FastAPI()
    app.include_router(metrics_router)
    reader = _FakeReader()
    app.state.ch_reader = reader
    return TestClient(app), reader


def _series(minutes: int):
    client, reader = _client()
    response = client.get(f"/metrics/{SERVER}/{METRIC}", params={"minutes": minutes})
    return response, reader


class TestSeriesSource:
    def test_a_day_is_read_from_raw_samples(self):
        response, reader = _series(settings.metrics_query_max_minutes)

        assert response.status_code == 200
        assert reader.calls == [("raw", 1440)]

    def test_longer_windows_are_read_from_the_hourly_rollup(self):
        response, reader = _series(7 * 1440)

        assert response.status_code == 200
        assert reader.calls == [("hourly", 7 * 1440)]
        assert response.json()["data"] == [{"timestamp": "2026-11-03T12:00:00.000Z", "value": 42.0}]

    def test_window_is_capped_at_the_history_limit(self):
        response, reader = _series(settings.metrics_history_max_days * 1440 + 1)

        assert response.status_code == 422
        assert reader.calls == []
