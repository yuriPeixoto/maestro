"""
Episodes endpoint: newest first, with their explanation, and "ongoing" only while
the worker keeps the episode fresh.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.anomalies import router as anomalies_router

SERVER = "web-1"


class _Result:
    def __init__(self, rows):
        self.result_rows = rows


class _ClickHouse:
    def __init__(self, rows):
        self.rows = rows
        self.parameters = None

    async def query(self, sql, parameters=None, settings=None):
        self.parameters = parameters
        return _Result(self.rows)


def _deviation(metric: str = "cpu_usage_percent") -> dict:
    return {"metric": metric, "value": 44.0, "z": 12.5, "normal_low": 5.0, "normal_high": 8.0,
            "peak_at": "2026-11-04T01:10:00+00:00"}


def _row(started: datetime, minutes: int, is_open: bool) -> tuple:
    naive = started.replace(tzinfo=None)  # ClickHouse returns naive UTC datetimes
    return (SERVER, naive, naive + timedelta(minutes=minutes), int(is_open), json.dumps([_deviation()]))


def _get(rows, **params):
    app = FastAPI()
    app.include_router(anomalies_router)
    clickhouse = _ClickHouse(rows)
    app.state.ch_client = clickhouse
    return TestClient(app).get(f"/anomalies/{SERVER}/episodes", params=params), clickhouse


def test_episodes_carry_their_explanation():
    started = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=3)

    resp, _ = _get([_row(started, 20, is_open=False)])

    assert resp.status_code == 200
    (episode,) = resp.json()
    assert episode["minutes"] == 20
    assert episode["ongoing"] is False
    assert episode["started_at"].endswith("Z")
    assert episode["deviations"][0]["metric"] == "cpu_usage_percent"


def test_an_open_episode_is_ongoing_only_while_fresh():
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    fresh = _row(now - timedelta(minutes=10), 9, is_open=True)
    abandoned = _row(now - timedelta(hours=2), 9, is_open=True)

    resp, _ = _get([fresh, abandoned])

    assert [e["ongoing"] for e in resp.json()] == [True, False]


def test_window_is_bounded():
    resp, clickhouse = _get([], hours=48)
    assert resp.status_code == 200
    assert datetime.now(timezone.utc) - clickhouse.parameters["since"] >= timedelta(hours=48)

    resp, _ = _get([], hours=24 * 31)
    assert resp.status_code == 422
