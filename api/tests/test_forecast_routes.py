"""
Capacity endpoints: route order, the real current value and collection progress.

A minimal app mounts only the forecasts router (the real app's lifespan needs
ClickHouse and Redis), with an in-memory reader and Redis.
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import forecasts
from app.forecasts import router as forecasts_router
from app.ml.forecaster import ForecastPoint, compute_runway, forecast_maturity

SERVER = "web-1"


class _FakeRedis:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    async def get(self, key: str) -> str | None:
        return self._values.get(key)

    async def aclose(self) -> None:
        return None


class _FakeReader:
    def __init__(self, days_with_data: int, current: dict[str, float]) -> None:
        self._days_with_data = days_with_data
        self._current = current

    async def get_daily_aggregates(self, server_id: str, metric_name: str, days: int = 60) -> list[dict]:
        return [{"date": f"2026-01-{i:02d}", "avg_value": 1.0} for i in range(self._days_with_data)]

    async def get_status_metric_value(self, server_id: str, metric_name: str) -> float | None:
        return self._current.get(metric_name)


def _cached_forecast(metric_name: str, yhats: list[float]) -> str:
    return json.dumps({
        "server_id": SERVER,
        "metric_name": metric_name,
        "status": "ok",
        "horizon_days": len(yhats),
        "trained_at": "2026-10-30T00:00:00+00:00",
        "points": [
            {"date": f"2026-11-{i + 1:02d}", "yhat": y, "yhat_lower": y - 1, "yhat_upper": y + 1}
            for i, y in enumerate(yhats)
        ],
    })


def _client(monkeypatch, *, days: int = 17, current: dict | None = None, cached: dict | None = None) -> TestClient:
    monkeypatch.setattr(forecasts.aioredis, "from_url", lambda *a, **kw: _FakeRedis(cached or {}))
    app = FastAPI()
    app.include_router(forecasts_router)
    app.state.ch_reader = _FakeReader(days, current or {})
    return TestClient(app)


def _disk_key() -> str:
    return forecasts._forecast_key(SERVER, "disk_usage_percent")


class TestRouteOrder:
    def test_runway_is_not_captured_as_a_metric_name(self, monkeypatch):
        response = _client(monkeypatch).get(f"/forecasts/{SERVER}/runway")

        assert response.status_code == 200
        assert [m["metric_name"] for m in response.json()["metrics"]] == forecasts._FORECAST_METRICS

    def test_a_metric_forecast_is_still_reachable(self, monkeypatch):
        cached = {_disk_key(): _cached_forecast("disk_usage_percent", [50.0])}

        response = _client(monkeypatch, cached=cached).get(f"/forecasts/{SERVER}/disk_usage_percent")

        assert response.status_code == 200
        assert response.json()["metric_name"] == "disk_usage_percent"


class TestRunwayValues:
    def test_current_value_is_measured_not_the_first_forecast_point(self, monkeypatch):
        cached = {_disk_key(): _cached_forecast("disk_usage_percent", [60.0, 61.0])}

        body = _client(monkeypatch, current={"disk_usage_percent": 47.0}, cached=cached).get(
            f"/forecasts/{SERVER}/runway"
        ).json()

        disk = next(m for m in body["metrics"] if m["metric_name"] == "disk_usage_percent")
        assert disk["current_value"] == 47.0
        assert disk["days_to_threshold"] is None
        assert disk["status"] == "safe"

    def test_value_is_shown_while_the_forecast_is_not_ready(self, monkeypatch):
        body = _client(monkeypatch, current={"disk_usage_percent": 47.0}).get(
            f"/forecasts/{SERVER}/runway"
        ).json()

        disk = next(m for m in body["metrics"] if m["metric_name"] == "disk_usage_percent")
        assert disk["current_value"] == 47.0
        assert disk["status"] == "no_data"

    def test_metric_already_past_the_threshold_has_zero_days(self, monkeypatch):
        cached = {_disk_key(): _cached_forecast("disk_usage_percent", [93.0])}

        body = _client(monkeypatch, current={"disk_usage_percent": 92.0}, cached=cached).get(
            f"/forecasts/{SERVER}/runway"
        ).json()

        disk = next(m for m in body["metrics"] if m["metric_name"] == "disk_usage_percent")
        assert disk["days_to_threshold"] == 0

    def test_first_forecast_point_is_tomorrow(self):
        points = [ForecastPoint(date="2026-11-01", yhat=95.0, yhat_lower=94.0, yhat_upper=96.0)]

        assert compute_runway(points, threshold=90.0) == 1


class TestCollectionProgress:
    @pytest.mark.parametrize(
        ("days", "state"),
        [(0, "learning"), (6, "learning"), (7, "preliminary"), (13, "preliminary"),
         (14, "evolving"), (59, "evolving"), (60, "complete"), (90, "complete")],
    )
    def test_stage_boundaries(self, days, state):
        assert forecast_maturity(days) == state

    def test_reports_when_the_window_fills_up(self):
        progress = forecasts._collection_progress(17, date(2026, 10, 30))

        assert progress.days_collected == 17
        assert progress.state == "evolving"
        assert progress.complete_on == "2026-12-12"

    def test_never_counts_past_the_window(self):
        progress = forecasts._collection_progress(61, date(2026, 10, 30))

        assert progress.days_collected == 60
        assert progress.state == "complete"
        assert progress.complete_on is None

    def test_runway_carries_the_progress(self, monkeypatch):
        body = _client(monkeypatch, days=3).get(f"/forecasts/{SERVER}/runway").json()

        assert body["horizon_days"] == 14
        assert body["collection"]["days_collected"] == 3
        assert body["collection"]["state"] == "learning"
