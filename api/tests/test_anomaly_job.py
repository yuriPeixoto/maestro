"""
The anomaly job scores settled minutes once, and writes episodes with what was
unusual. ClickHouse and Redis are replaced by in-memory fakes; the fake reads its
queries by their parameters, so the SQL text itself is covered by the smoke test.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app import anomaly_job
from app.anomaly_job import AnomalyJob
from app.anomaly_store import ANOMALOUS_SCORE
from app.ml.frames import ANOMALY_METRICS

SERVER = "web-1"
NOW = datetime(2026, 11, 10, 12, 0, 30, tzinfo=timezone.utc)


def _metrics(start: datetime, end: datetime) -> pd.DataFrame:
    """A steady server: CPU around 10%, everything else flat with a little noise."""
    index = pd.date_range(start, end, freq="1min", inclusive="left", name="minute")
    rng = np.random.default_rng(int(start.timestamp()) % 1000)
    frame = pd.DataFrame({m: 100 + rng.normal(0, 1, len(index)) for m in ANOMALY_METRICS}, index=index)
    frame["cpu_usage_percent"] = 10 + rng.normal(0, 1, len(index))
    return frame


class _Result:
    def __init__(self, rows):
        self.result_rows = rows


class _ClickHouse:
    """Serves the minute frame from `incident`-patched data and stores inserts."""

    def __init__(self, incident: tuple[datetime, datetime] | None = None) -> None:
        self.incident = incident
        self.scores: list[list] = []
        self.episodes: list[list] = []

    async def query(self, sql, parameters=None, settings=None):
        if "anomaly_scores" in sql:
            return _Result(self._flags(parameters["since"]))
        frame = _metrics(parameters["start"], parameters["end"])
        if self.incident:
            hit = (frame.index >= self.incident[0]) & (frame.index < self.incident[1])
            frame.loc[hit, "cpu_usage_percent"] = 90.0
        rows = [(minute, metric, value) for minute, row in frame.iterrows() for metric, value in row.items()]
        return _Result(rows)

    async def insert(self, table, data, column_names):
        (self.scores if table == "anomaly_scores" else self.episodes).extend(data)

    def _flags(self, since):
        by_minute: dict[datetime, float] = {}
        for _server, _metric, minute, score, _model in self.scores:
            if minute >= since:
                by_minute[minute] = max(by_minute.get(minute, 0.0), score)
        return [(m, s >= ANOMALOUS_SCORE) for m, s in sorted(by_minute.items())]


class _Redis:
    async def hkeys(self, _key):
        return [SERVER]


@pytest.fixture(autouse=True)
def _fit_in_process(monkeypatch):
    async def inline(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr(anomaly_job, "run_in_ml_process", inline)


@pytest.mark.asyncio
async def test_settled_minutes_are_scored_once():
    clickhouse = _ClickHouse()
    clock = [NOW]
    job = AnomalyJob(clickhouse, _Redis(), clock=lambda: clock[0])

    await job.run_once()
    first = len(clickhouse.scores)
    clock[0] = NOW + timedelta(minutes=1)
    await job.run_once()

    settled = NOW.replace(second=0) - timedelta(minutes=anomaly_job.SETTLE_MINUTES)
    assert first == len(ANOMALY_METRICS) * int(anomaly_job.EPISODE_WINDOW / timedelta(minutes=1))
    assert max(row[2] for row in clickhouse.scores[:first]) == settled - timedelta(minutes=1)
    assert len(clickhouse.scores) - first == len(ANOMALY_METRICS)
    assert clickhouse.episodes == []


@pytest.mark.asyncio
async def test_an_incident_becomes_an_open_episode_with_its_explanation():
    settled = NOW.replace(second=0) - timedelta(minutes=anomaly_job.SETTLE_MINUTES)
    incident = (settled - timedelta(minutes=20), settled)
    clickhouse = _ClickHouse(incident)
    # The baseline must not learn the incident: fit it on a clean history first.
    clean = _ClickHouse()
    job = AnomalyJob(clean, _Redis(), clock=lambda: NOW - timedelta(hours=1))
    await job.run_once()
    job._client = clickhouse
    job._clock = lambda: NOW

    await job.run_once()

    (server, started, ended, is_open, metrics, peak_z, details, _updated) = clickhouse.episodes[-1]
    assert server == SERVER
    assert (started, ended) == (incident[0], incident[1])
    assert is_open == 1
    assert metrics == ["cpu_usage_percent"]
    cpu = json.loads(details)[0]
    assert cpu["value"] == 90.0
    assert cpu["normal_high"] < 20
    assert peak_z > 5


@pytest.mark.asyncio
async def test_after_a_restart_older_episodes_of_the_window_are_written_too():
    settled = NOW.replace(second=0) - timedelta(minutes=anomaly_job.SETTLE_MINUTES)
    incident = (settled - timedelta(hours=3), settled - timedelta(hours=2, minutes=40))
    clean = _ClickHouse()
    job = AnomalyJob(clean, _Redis(), clock=lambda: NOW - timedelta(days=1))
    await job.run_once()
    restarted = AnomalyJob(_ClickHouse(incident), _Redis(), clock=lambda: NOW)
    restarted._states = {s: type(st)(baseline=st.baseline, fitted_at=NOW) for s, st in job._states.items()}

    await restarted.run_once()

    (episode,) = restarted._client.episodes
    assert (episode[1], episode[2], episode[3]) == (incident[0], incident[1], 0)


@pytest.mark.asyncio
async def test_waits_for_a_day_of_history():
    class _Young(_ClickHouse):
        async def query(self, sql, parameters=None, settings=None):
            if "anomaly_scores" not in sql and parameters["end"] - parameters["start"] > timedelta(days=1):
                parameters = {**parameters, "start": parameters["end"] - timedelta(hours=6)}
            return await super().query(sql, parameters, settings)

    clickhouse = _Young()
    await AnomalyJob(clickhouse, _Redis(), clock=lambda: NOW).run_once()

    assert clickhouse.scores == []
