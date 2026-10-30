"""
Which value status and alert rules are judged on.

The reader runs against a fake ClickHouse client that answers from canned rows,
so these tests pin the query shape and the None handling, not ClickHouse itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from app.clickhouse import ClickHouseReader


@dataclass
class _Result:
    result_rows: list


@dataclass
class _FakeClient:
    rows: list
    queries: list[str] = field(default_factory=list)

    async def query(self, sql: str, parameters: dict | None = None) -> _Result:
        self.queries.append(sql)
        return _Result(self.rows)


def _reader(rows: list) -> tuple[ClickHouseReader, _FakeClient]:
    client = _FakeClient(rows)
    return ClickHouseReader(client), client


class TestLatestValue:
    @pytest.mark.asyncio
    async def test_returns_the_newest_sample_not_the_window_peak(self):
        reader, client = _reader([(12.5,)])

        assert await reader.get_latest_metric_value("s1", "memory_usage_percent") == 12.5
        assert "MAX(" not in client.queries[0].upper()
        assert "ORDER BY timestamp DESC LIMIT 1" in client.queries[0]

    @pytest.mark.asyncio
    async def test_silent_metric_is_none(self):
        reader, _ = _reader([])

        assert await reader.get_latest_metric_value("s1", "memory_usage_percent") is None


class TestWindowAverage:
    @pytest.mark.asyncio
    async def test_empty_window_is_none_even_though_clickhouse_returns_nan(self):
        reader, _ = _reader([(float("nan"), 0)])

        assert await reader.get_metric_window_average("s1", "cpu_usage_percent") is None

    @pytest.mark.asyncio
    async def test_returns_the_average(self):
        reader, _ = _reader([(47.7, 20)])

        assert await reader.get_metric_window_average("s1", "cpu_usage_percent") == 47.7


class TestStatusValue:
    @pytest.mark.asyncio
    async def test_cpu_uses_the_window_average(self):
        reader, client = _reader([(47.7, 20)])

        assert await reader.get_status_metric_value("s1", "cpu_usage_percent") == 47.7
        assert "avg(value)" in client.queries[0]

    @pytest.mark.asyncio
    async def test_other_metrics_use_the_latest_sample(self):
        reader, client = _reader([(61.0,)])

        assert await reader.get_status_metric_value("s1", "disk_usage_percent") == 61.0
        assert "avg(value)" not in client.queries[0]


class TestOpenAlerts:
    @pytest.mark.asyncio
    async def test_keeps_only_rules_whose_latest_event_is_firing(self):
        rule_id = uuid4()
        reader, client = _reader([(rule_id, "critical", "FIRING")])

        assert await reader.get_open_alert_severities("s1") == {str(rule_id): "critical"}
        assert "HAVING last_state = 'FIRING'" in client.queries[0]
