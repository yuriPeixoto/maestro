"""
Rules and alert state in Postgres: the rule routes, what the database refuses,
the compare-and-set that keeps one alert from firing twice, and the evaluator's
cycle (fire, cooldown, resolve, standing by behind the advisory lock).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import alert_evaluator, alert_store, db
from app.alert_store import STATE_FIRING, STATE_INACTIVE, STATE_RESOLVED, AlertChannel, AlertRule, AlertState, RuleToEvaluate
from app.alerts import router
from tests.conftest import act_as

_NOW = datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc)


def _rule(server_id: str = "web-1", threshold: float = 90.0, cooldown: int = 5) -> AlertRule:
    return AlertRule(
        rule_id=uuid4(), server_id=server_id, metric_name="cpu_usage_percent", operator=">=",
        threshold=threshold, severity="critical", cooldown_minutes=cooldown, created_at=_NOW,
    )


class _ClickHouse:
    def __init__(self, value: float | None = None, fail_inserts: bool = False) -> None:
        self.value = value
        self.fail_inserts = fail_inserts
        self.events: list = []
        self.records: list = []

    async def get_status_metric_value(self, _server_id, _metric):
        return self.value

    async def get_latest_anomaly_score(self, _server_id, _metric):
        return None

    async def insert_alert_event(self, event) -> None:
        if self.fail_inserts:
            raise RuntimeError("ClickHouse is down")
        self.events.append(event)

    async def insert_notification_records(self, records) -> None:
        self.records.extend(records)

    async def get_alert_rule_patterns(self, _server_id):
        return {}


class _Redis:
    async def hget(self, _key, _field):
        return None


async def _item(rule_id) -> RuleToEvaluate:
    [item] = [i for i in await alert_store.rules_to_evaluate(["web-1"]) if i.rule.rule_id == rule_id]
    return item


async def _state(rule_id) -> AlertState:
    return (await _item(rule_id)).state


@pytest.fixture
def client(postgres) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    act_as(app, role="operator")
    app.state.ch_reader = _ClickHouse()
    app.state.vuln_redis = _Redis()
    return TestClient(app)


_BODY = {"metric_name": "cpu_usage_percent", "operator": ">=", "threshold": 90, "severity": "critical"}


class TestRuleRoutes:
    def test_create_list_and_delete(self, client):
        created = client.post("/alerts/web-1/rules", json=_BODY)

        assert created.status_code == 201
        rule_id = created.json()["rule_id"]
        assert [r["rule_id"] for r in client.get("/alerts/web-1/rules").json()["rules"]] == [rule_id]
        assert client.delete(f"/alerts/web-2/rules/{rule_id}").status_code == 404
        assert client.delete(f"/alerts/web-1/rules/{rule_id}").status_code == 204
        assert client.get("/alerts/web-1/rules").json()["rules"] == []
        assert client.delete(f"/alerts/web-1/rules/{rule_id}").status_code == 404

    def test_the_same_rule_twice_is_a_conflict(self, client):
        assert client.post("/alerts/web-1/rules", json=_BODY).status_code == 201

        assert client.post("/alerts/web-1/rules", json=_BODY).status_code == 409
        assert client.post("/alerts/web-2/rules", json=_BODY).status_code == 201

    def test_a_deleted_rule_can_be_created_again(self, client):
        rule_id = client.post("/alerts/web-1/rules", json=_BODY).json()["rule_id"]
        client.delete(f"/alerts/web-1/rules/{rule_id}")

        assert client.post("/alerts/web-1/rules", json=_BODY).status_code == 201

    @pytest.mark.asyncio
    async def test_patterns_show_a_firing_rule(self, client):
        rule = await alert_store.create_rule(_rule())
        firing = AlertState(state=STATE_FIRING, last_fired_at=_NOW)
        await alert_store.change_state(rule.rule_id, "web-1", await _state(rule.rule_id), firing, uuid4())

        [pattern] = client.get("/alerts/web-1/rule-patterns").json()["patterns"]
        assert pattern["state"] == "firing"


class TestDatabaseRefuses:
    @pytest.mark.asyncio
    async def test_an_unknown_operator(self, postgres):
        rule = _rule()
        rule.operator = "!="

        with pytest.raises(Exception, match="alert_rules_operator_check"):
            await alert_store.create_rule(rule)

    @pytest.mark.asyncio
    async def test_a_channel_config_that_is_not_an_object(self, postgres):
        with pytest.raises(Exception, match="alert_channels_config_check"):
            async with db.session() as s:
                await s.execute(text(
                    "INSERT INTO alert_channels (channel_id, server_id, channel_type, config)"
                    " VALUES (gen_random_uuid(), 'web-1', 'webhook', '[]'::jsonb)"
                ))

    @pytest.mark.asyncio
    async def test_updated_at_follows_a_change_made_by_hand(self, postgres):
        rule = await alert_store.create_rule(_rule())
        async with db.session() as s:
            before = await s.scalar(text("SELECT updated_at FROM alert_rules WHERE rule_id = :r"), {"r": rule.rule_id})
        async with db.session() as s:
            await s.execute(text("UPDATE alert_rules SET threshold = 95 WHERE rule_id = :r"), {"r": rule.rule_id})
            after = await s.scalar(text("SELECT updated_at FROM alert_rules WHERE rule_id = :r"), {"r": rule.rule_id})

        assert after > before


class TestDeleteRule:
    @pytest.mark.asyncio
    async def test_takes_the_channels_that_only_served_it(self, postgres):
        rule = await alert_store.create_rule(_rule())
        for rule_id in (rule.rule_id, None):
            await alert_store.create_channel(AlertChannel(
                channel_id=uuid4(), rule_id=rule_id, server_id="web-1", channel_type="telegram",
                config={}, created_at=_NOW,
            ))

        await alert_store.delete_rule("web-1", rule.rule_id)

        assert [ch.rule_id for ch in await alert_store.list_channels("web-1")] == [None]


class TestCompareAndSet:
    @pytest.mark.asyncio
    async def test_only_the_first_of_two_changes_from_one_read_applies(self, postgres):
        rule = await alert_store.create_rule(_rule())
        read = await _state(rule.rule_id)
        firing = AlertState(state=STATE_FIRING, last_fired_at=_NOW)

        assert await alert_store.change_state(rule.rule_id, "web-1", read, firing, uuid4())
        assert not await alert_store.change_state(rule.rule_id, "web-1", read, firing, uuid4())
        assert (await _state(rule.rule_id)).version == read.version + 1

    @pytest.mark.asyncio
    async def test_a_missing_state_row_is_created_once(self, postgres):
        rule = await alert_store.create_rule(_rule())
        async with db.session() as s:
            await s.execute(text("DELETE FROM alert_state"))
        read = await _state(rule.rule_id)
        firing = AlertState(state=STATE_FIRING, last_fired_at=_NOW)

        assert read.version is None
        assert await alert_store.change_state(rule.rule_id, "web-1", read, firing, uuid4())
        assert not await alert_store.change_state(rule.rule_id, "web-1", read, firing, uuid4())


class TestEvaluator:
    @pytest.mark.asyncio
    async def test_fires_once_then_resolves(self, postgres):
        rule = await alert_store.create_rule(_rule())
        clickhouse = _ClickHouse(value=95.0)

        await alert_evaluator._evaluate_rule(await _item(rule.rule_id), clickhouse, clickhouse, _Redis())
        await alert_evaluator._evaluate_rule(await _item(rule.rule_id), clickhouse, clickhouse, _Redis())
        clickhouse.value = 50.0
        await alert_evaluator._evaluate_rule(await _item(rule.rule_id), clickhouse, clickhouse, _Redis())

        assert [e.state for e in clickhouse.events] == [STATE_FIRING, STATE_RESOLVED]
        state = await _state(rule.rule_id)
        assert state.state == STATE_RESOLVED
        assert state.last_event_id == clickhouse.events[-1].event_id

    @pytest.mark.asyncio
    async def test_a_stale_read_does_not_fire_again(self, postgres):
        rule = await alert_store.create_rule(_rule())
        clickhouse = _ClickHouse(value=95.0)
        stale = await _item(rule.rule_id)

        await alert_evaluator._evaluate_rule(stale, clickhouse, clickhouse, _Redis())
        await alert_evaluator._evaluate_rule(stale, clickhouse, clickhouse, _Redis())

        assert len(clickhouse.events) == 1

    @pytest.mark.asyncio
    async def test_waits_out_the_cooldown_after_resolving(self, postgres):
        rule = await alert_store.create_rule(_rule(cooldown=30))
        read = await _state(rule.rule_id)
        resolved = AlertState(state=STATE_RESOLVED, last_resolved_at=datetime.now(timezone.utc) - timedelta(minutes=5))
        await alert_store.change_state(rule.rule_id, "web-1", read, resolved, uuid4())
        clickhouse = _ClickHouse(value=95.0)

        await alert_evaluator._evaluate_rule(await _item(rule.rule_id), clickhouse, clickhouse, _Redis())

        assert clickhouse.events == []

    @pytest.mark.asyncio
    async def test_fires_even_when_the_history_insert_fails(self, postgres, monkeypatch):
        rule = await alert_store.create_rule(_rule())
        notified: list = []

        async def notify(event, kind, _writer, *_where):
            notified.append(kind)

        monkeypatch.setattr(alert_evaluator, "_notify", notify)
        clickhouse = _ClickHouse(value=95.0, fail_inserts=True)

        await alert_evaluator._evaluate_rule(await _item(rule.rule_id), clickhouse, clickhouse, _Redis())

        assert notified == ["firing"]
        assert (await _state(rule.rule_id)).state == STATE_FIRING

    @pytest.mark.asyncio
    async def test_inactive_rule_without_data_is_left_alone(self, postgres):
        rule = await alert_store.create_rule(_rule())
        clickhouse = _ClickHouse(value=None)

        await alert_evaluator._evaluate_rule(await _item(rule.rule_id), clickhouse, clickhouse, _Redis())

        assert (await _state(rule.rule_id)).state == STATE_INACTIVE


class TestAdvisoryLock:
    @pytest.mark.asyncio
    async def test_one_holder_at_a_time(self, postgres):
        first, second = db.AdvisoryLock(alert_evaluator.EVALUATOR_LOCK_KEY), db.AdvisoryLock(
            alert_evaluator.EVALUATOR_LOCK_KEY,
        )
        try:
            assert await first.hold()
            assert await first.hold()
            assert not await second.hold()
            await first.release()
            assert await second.hold()
        finally:
            await first.release()
            await second.release()

    @pytest.mark.asyncio
    async def test_connections_carry_the_application_name(self, postgres, monkeypatch):
        monkeypatch.setattr(db, "_application_name", "maestro-test")
        await db.dispose_engine()
        async with db.session() as s:
            name = await s.scalar(text("SELECT current_setting('application_name')"))
            timeout = await s.scalar(text("SELECT current_setting('statement_timeout')"))

        assert (name, timeout) == ("maestro-test", "15s")
