"""
The one-time copy of 0.1.0's alert configuration and state into Postgres:
safe to run again, duplicates and orphans accounted for, and every source row
checked in Postgres at the end.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from sqlalchemy import select

from app import alert_store, db, import_alerting
from app.alert_store import STATE_FIRING, STATE_INACTIVE
from app.config import settings
from app.import_alerting import (
    ALREADY,
    COPIED,
    DUPLICATE,
    ORPHAN,
    Sources,
    import_sources,
    legacy_webhook_channel_id,
    missing_in_postgres,
    parse_state,
    read_sources,
)
from app.models import AlertDefaultsApplied


async def _servers_with_defaults() -> set[str]:
    async with db.session() as s:
        return set(await s.scalars(select(AlertDefaultsApplied.server_id)))

_NOW = datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc)
_NIL = UUID(int=0)


def _ch_rule(rule_id: UUID, server_id: str = "web-1", metric: str = "cpu_percent", enabled: int = 1) -> tuple:
    # rule_id, server_id, metric_name, operator, threshold, severity, cooldown_minutes, created_at, alert_mode, ml
    return (rule_id, server_id, metric, ">=", 80.0, "critical", 15, _NOW.replace(tzinfo=None), "static", 0.7)


class _Result:
    def __init__(self, rows: list) -> None:
        self.result_rows = rows


class _ClickHouse:
    def __init__(self, rules: list, channels: list) -> None:
        self.rules, self.channels = rules, channels
        self.queries: list[str] = []

    async def query(self, sql: str, parameters: dict | None = None) -> _Result:
        self.queries.append(sql)
        return _Result(self.rules if "alert_rules" in sql else self.channels)


class _Redis:
    def __init__(self, strings: dict, members: set) -> None:
        self.strings, self.members = strings, members
        self.writes = 0

    async def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        for key in list(self.strings):
            if key.startswith(prefix):
                yield key

    async def get(self, key):
        return self.strings.get(key)

    async def smembers(self, _key):
        return set(self.members)


def _sources() -> tuple[_ClickHouse, _Redis, dict[str, UUID]]:
    ids = {"cpu": uuid4(), "cpu_twin": uuid4(), "deleted": uuid4(), "chan": uuid4(), "chan_twin": uuid4(),
           "chan_orphan": uuid4(), "wide": uuid4()}
    clickhouse = _ClickHouse(
        rules=[_ch_rule(ids["cpu"]), _ch_rule(ids["cpu_twin"])],
        channels=[
            (ids["chan"], ids["cpu"], "web-1", "telegram", json.dumps({"chat_id": "42"}), _NOW.replace(tzinfo=None)),
            (ids["chan_twin"], ids["cpu_twin"], "web-1", "telegram", "{}", _NOW.replace(tzinfo=None)),
            (ids["chan_orphan"], ids["deleted"], "web-1", "telegram", "{}", _NOW.replace(tzinfo=None)),
            (ids["wide"], _NIL, "web-1", "slack", json.dumps({"webhook_url": "https://s.example.com/x"}),
             _NOW.replace(tzinfo=None)),
        ],
    )
    firing = json.dumps({"state": "FIRING", "last_fired_at": _NOW.isoformat(), "last_resolved_at": None})
    redis = _Redis(
        strings={
            f"maestro:alert_state:web-1:{ids['cpu']}": firing,
            "maestro:webhook:web-2": "https://hooks.example.com/legacy",
        },
        members={"web-1", "web-2"},
    )
    return clickhouse, redis, ids


class TestParseState:
    def test_reads_a_0_1_0_state(self):
        state = parse_state(json.dumps({"state": "RESOLVED", "last_fired_at": "2026-11-01T10:00:00",
                                        "last_resolved_at": "2026-11-01T10:05:00+00:00"}))

        assert state.state == "RESOLVED"
        assert state.last_fired_at.tzinfo is not None

    @pytest.mark.parametrize("raw", ["", "nope", '{"state": "WEIRD"}', '{"last_fired_at": null}'])
    def test_unreadable_is_none(self, raw):
        assert parse_state(raw) is None


class TestReadSources:
    @pytest.mark.asyncio
    async def test_renames_old_metrics_and_turns_the_legacy_webhook_into_a_channel(self):
        clickhouse, redis, ids = _sources()

        sources = await read_sources(clickhouse, redis)

        assert {r["metric_name"] for r in sources.rules} == {"cpu_usage_percent"}
        assert all("FINAL WHERE enabled = 1" in q for q in clickhouse.queries)
        webhook = next(c for c in sources.channels if c["server_id"] == "web-2")
        assert webhook["channel_id"] == legacy_webhook_channel_id("web-2")
        assert next(c for c in sources.channels if c["channel_id"] == ids["wide"])["rule_id"] is None
        assert sources.states[ids["cpu"]].state == STATE_FIRING
        assert sources.defaults_applied == ["web-1", "web-2"]


class TestImport:
    @pytest.mark.asyncio
    async def test_copies_everything_and_checks_it(self, postgres):
        clickhouse, redis, ids = _sources()
        sources = await read_sources(clickhouse, redis)

        report = await import_sources(sources)

        assert report.outcomes["rules"] == {COPIED: 1, DUPLICATE: 1}
        assert report.outcomes["channels"] == {COPIED: 4, ORPHAN: 1}
        assert report.rule_ids[ids["cpu_twin"]] == ids["cpu"]
        assert await missing_in_postgres(sources, report) == []
        channels = {ch.channel_id: ch for ch in await alert_store.list_channels("web-1")}
        assert channels[ids["chan_twin"]].rule_id == ids["cpu"]  # follows the rule that stays
        assert channels[ids["wide"]].rule_id is None
        assert channels[ids["chan"]].config == {"chat_id": "42"}
        assert [ch.config for ch in await alert_store.list_channels("web-2")] == [
            {"url": "https://hooks.example.com/legacy"},
        ]
        assert await alert_store.firing_severities("web-1") == {str(ids["cpu"]): "critical"}
        assert await _servers_with_defaults() == {"web-1", "web-2"}

    @pytest.mark.asyncio
    async def test_second_run_duplicates_nothing_and_keeps_newer_state(self, postgres):
        clickhouse, redis, ids = _sources()
        sources = await read_sources(clickhouse, redis)
        await import_sources(sources)
        [item] = await alert_store.rules_to_evaluate(["web-1"])
        resolved = alert_store.AlertState(state="RESOLVED", last_fired_at=_NOW, last_resolved_at=_NOW)
        await alert_store.change_state(ids["cpu"], "web-1", item.state, resolved, uuid4())

        report = await import_sources(await read_sources(clickhouse, redis))

        assert report.outcomes["rules"] == {ALREADY: 1, DUPLICATE: 1}
        assert report.outcomes["channels"] == {ALREADY: 4, ORPHAN: 1}
        assert report.outcomes["defaults_applied"] == {ALREADY: 2}
        assert len(await alert_store.list_rules("web-1")) == 1
        assert len(await alert_store.list_channels("web-1")) == 3
        assert await alert_store.firing_severities("web-1") == {}

    @pytest.mark.asyncio
    async def test_a_rule_deleted_after_the_copy_stays_deleted(self, postgres):
        clickhouse, redis, ids = _sources()
        sources = await read_sources(clickhouse, redis)
        await import_sources(sources)
        await alert_store.delete_rule("web-1", ids["cpu"])

        report = await import_sources(sources)

        assert report.outcomes["rules"][ALREADY] == 1
        assert await alert_store.list_rules("web-1") == []

    @pytest.mark.asyncio
    async def test_missing_rows_are_reported(self, postgres):
        sources = Sources(defaults_applied=["web-9"])
        report = import_alerting.Report()

        assert await missing_in_postgres(sources, report) == ["defaults of web-9"]

    @pytest.mark.asyncio
    async def test_rule_without_a_redis_state_starts_inactive(self, postgres):
        clickhouse, _redis, ids = _sources()
        sources = await read_sources(clickhouse, _Redis({}, set()))

        await import_sources(sources)

        [item] = await alert_store.rules_to_evaluate(["web-1"])
        assert item.state.state == STATE_INACTIVE
        assert settings.default_rules_applied_key  # the set is read through settings
