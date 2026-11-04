"""
CPU and memory capacity: the daily peak against the critical limit, and the disk
trend reported since its last level shift.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.forecasts import router as forecasts_router
from app.ml.forecaster import forecast
from app.peaks import DailyPeak, summarize

SERVER = "web-1"


def _days(peaks: list[float], above: int = 0) -> list[DailyPeak]:
    start = date(2026, 10, 21)
    return [DailyPeak(start + timedelta(days=i), p, above) for i, p in enumerate(peaks)]


class TestSummary:
    def test_headroom_is_measured_on_the_worst_day(self):
        summary = summarize("cpu_usage_percent", _days([26, 36, 69, 29]))

        assert summary.worst.peak == 69
        assert summary.headroom_pct == 11.0
        assert summary.status == "watch"

    def test_plenty_of_headroom_is_safe(self):
        assert summarize("memory_usage_percent", _days([40.9, 44.6, 38.0])).status == "safe"

    def test_a_peak_above_the_limit_is_critical(self):
        summary = summarize("cpu_usage_percent", _days([50, 85], above=12))

        assert summary.status == "critical"
        assert summary.minutes_above_critical == 24

    def test_trend_needs_a_week_and_a_real_change(self):
        assert summarize("cpu_usage_percent", _days([20, 30, 40])).trend == "unknown"
        assert summarize("cpu_usage_percent", _days([30, 31, 29, 30, 32, 30, 31, 29])).trend == "stable"
        assert summarize("cpu_usage_percent", _days(list(np.linspace(20, 40, 10)))).trend == "rising"

    def test_no_data(self):
        summary = summarize("cpu_usage_percent", [])

        assert (summary.status, summary.worst, summary.headroom_pct) == ("no_data", None, None)


class _Result:
    def __init__(self, rows):
        self.result_rows = rows


class _ClickHouse:
    async def query(self, sql, parameters=None, settings=None):
        rows = [("cpu_usage_percent", date(2026, 11, d), 20.0 + d, 0) for d in range(1, 4)]
        return _Result(rows)


def test_peaks_route_reports_both_metrics():
    app = FastAPI()
    app.include_router(forecasts_router)
    app.state.ch_client = _ClickHouse()

    body = TestClient(app).get(f"/forecasts/{SERVER}/peaks", params={"days": 7}).json()

    cpu, memory = body["metrics"]
    assert body["window_minutes"] == 5
    assert cpu["worst"] == {"date": "2026-11-03", "peak": 23.0, "minutes_above_critical": 0}
    assert cpu["status"] == "safe"
    assert memory["status"] == "no_data"


def test_forecast_reports_the_trend_since_the_last_shift():
    values = list(np.linspace(45.6, 46.1, 13)) + [46.7] + list(47.2 + 0.04 * np.arange(9))
    daily = [{"date": (date(2026, 10, 13) + timedelta(days=i)).isoformat(), "avg_value": v}
             for i, v in enumerate(values)]

    result = forecast("web-1", "disk_usage_percent", daily, horizon_days=3)

    assert result.level_shift_on == "2026-10-27"
    assert abs(result.trend_per_day - 0.04) < 0.01
    assert result.points[0].yhat > values[-1]
