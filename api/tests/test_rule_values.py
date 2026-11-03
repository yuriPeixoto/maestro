"""
`heartbeat_age_seconds` lets a rule fire on a server that stopped reporting.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.rule_values import HEARTBEAT_AGE_METRIC, current_rule_value, heartbeat_age_seconds

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def _entry(last_seen: datetime) -> str:
    return json.dumps({"last_seen": last_seen.isoformat()})


class TestHeartbeatAge:
    def test_seconds_since_the_last_heartbeat(self):
        assert heartbeat_age_seconds(_entry(_NOW - timedelta(minutes=5)), _NOW) == 300

    def test_naive_timestamp_is_read_as_utc(self):
        naive = (_NOW - timedelta(seconds=30)).replace(tzinfo=None)

        assert heartbeat_age_seconds(_entry(naive), _NOW) == 30

    @pytest.mark.parametrize("raw", [None, "", "not json", '{"agent_version": "1"}'])
    def test_unreadable_entry_is_none(self, raw):
        assert heartbeat_age_seconds(raw, _NOW) is None


class _Redis:
    def __init__(self, entry: str | None) -> None:
        self.entry = entry

    async def hget(self, _key: str, _field: str) -> str | None:
        return self.entry


class _Reader:
    def __init__(self) -> None:
        self.asked: list[str] = []

    async def get_status_metric_value(self, _server_id: str, metric_name: str) -> float:
        self.asked.append(metric_name)
        return 42.0


class TestCurrentRuleValue:
    @pytest.mark.asyncio
    async def test_heartbeat_rule_reads_redis_not_clickhouse(self):
        reader = _Reader()
        redis = _Redis(_entry(datetime.now(timezone.utc) - timedelta(minutes=10)))

        value = await current_rule_value(reader, redis, "s1", HEARTBEAT_AGE_METRIC)

        assert value == pytest.approx(600, abs=5)
        assert reader.asked == []

    @pytest.mark.asyncio
    async def test_metric_rule_reads_the_status_value(self):
        reader = _Reader()

        assert await current_rule_value(reader, _Redis(None), "s1", "disk_usage_percent") == 42.0
        assert reader.asked == ["disk_usage_percent"]
