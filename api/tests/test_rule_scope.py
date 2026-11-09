"""
Rules for every server, a group or one server: the most specific one wins per metric
and severity, a switched-off rule silences what it overrides, channels add up, state is
kept per rule and server, and the default rules become global ones once.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app import alert_store, db, server_store
from app.alert_store import STATE_FIRING, AlertChannel, AlertRule, AlertState
from app.default_rules import default_rules, ensure_global_default_rules
from app.models import AlertRuleRow, AlertStateRow, AuditLogRow
from app.rule_scope import SCOPE_GLOBAL, SCOPE_GROUP, SCOPE_SERVER, Place, effective, resolve
from app.scoped_alerts import router as scoped_router
from tests.conftest import act_as

_NOW = datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)


def _rule(
    scope: str = SCOPE_GLOBAL, server_id: str | None = None, group_id: int | None = None,
    threshold: float = 90.0, severity: str = "critical", metric: str = "cpu_usage_percent", enabled: bool = True,
) -> AlertRule:
    return AlertRule(
        rule_id=uuid4(), server_id=server_id, metric_name=metric, operator=">=", threshold=threshold,
        severity=severity, cooldown_minutes=5, created_at=_NOW, scope=scope, group_id=group_id, enabled=enabled,
    )


class TestPrecedence:
    """Pure: no database."""

    def test_server_beats_group_beats_global(self):
        everyone, group, own = _rule(threshold=80), _rule(SCOPE_GROUP, group_id=1, threshold=85), _rule(
            SCOPE_SERVER, server_id="db-1", threshold=95,
        )
        rules = [everyone, group, own]

        assert effective(rules, "db-1", 1) == [own]
        assert effective(rules, "db-2", 1) == [group]
        assert effective(rules, "web-1", 2) == [everyone]
        assert effective(rules, "web-1", None) == [everyone]

    def test_the_winner_lists_what_it_overrides(self):
        everyone, group = _rule(threshold=80), _rule(SCOPE_GROUP, group_id=1, threshold=85)

        [(winner, overridden)] = resolve([everyone, group], "db-1", 1)

        assert (winner, overridden) == (group, [everyone])

    def test_metric_and_severity_are_judged_apart(self):
        warning, critical = _rule(severity="warning", threshold=70), _rule(severity="critical")
        disk = _rule(metric="disk_usage_percent")
        own_critical = _rule(SCOPE_SERVER, server_id="web-1", threshold=99)

        winners = effective([warning, critical, disk, own_critical], "web-1", None)

        assert {(r.metric_name, r.severity, r.threshold) for r in winners} == {
            ("cpu_usage_percent", "warning", 70), ("cpu_usage_percent", "critical", 99),
            ("disk_usage_percent", "critical", 90),
        }

    def test_a_switched_off_rule_silences_the_inherited_one_only_there(self):
        everyone = _rule()
        off_here = _rule(SCOPE_SERVER, server_id="robot-1", enabled=False)

        assert effective([everyone, off_here], "robot-1", None) == []
        assert effective([everyone, off_here], "robot-2", None) == [everyone]

    def test_another_group_is_not_covered(self):
        assert effective([_rule(SCOPE_GROUP, group_id=1)], "web-1", 2) == []
        assert effective([_rule(SCOPE_GROUP, group_id=1)], "web-1", None) == []

    @pytest.mark.parametrize(("scope", "server_id", "group_id"), [
        (SCOPE_GLOBAL, "web-1", None), (SCOPE_GROUP, None, None), (SCOPE_SERVER, None, None),
        (SCOPE_SERVER, "web-1", 1), ("cluster", None, None),
    ])
    def test_a_place_must_be_coherent(self, scope, server_id, group_id):
        with pytest.raises(ValueError):
            Place(scope, server_id, group_id)


async def _group(name: str = "database") -> int:
    return (await server_store.create_group(name)).group_id


async def _server(server_id: str, group_id: int | None = None) -> None:
    await server_store.register_servers([server_id])
    if group_id is not None:
        await server_store.update_server(server_id, group_id=group_id)


class TestPrecedenceInPostgres:
    @pytest.mark.asyncio
    async def test_each_server_is_judged_by_its_winners(self, postgres):
        group_id = await _group()
        await _server("db-1", group_id)
        await _server("db-2", group_id)
        await _server("web-1")
        everyone = await alert_store.create_rule(_rule(threshold=80))
        group = await alert_store.create_rule(_rule(SCOPE_GROUP, group_id=group_id, threshold=85))
        own = await alert_store.create_rule(_rule(SCOPE_SERVER, server_id="db-1", threshold=95))

        items = await alert_store.rules_to_evaluate(["db-1", "db-2", "web-1"])

        assert {(i.server_id, i.rule.rule_id) for i in items} == {
            ("db-1", own.rule_id), ("db-2", group.rule_id), ("web-1", everyone.rule_id),
        }
        assert {i.server_id: i.group_id for i in items} == {"db-1": group_id, "db-2": group_id, "web-1": None}

    @pytest.mark.asyncio
    async def test_a_global_rule_keeps_one_state_per_server(self, postgres):
        rule = await alert_store.create_rule(_rule())
        firing = AlertState(state=STATE_FIRING, last_fired_at=_NOW)

        [item] = await alert_store.rules_to_evaluate(["web-1"])
        assert await alert_store.change_state(rule.rule_id, "web-1", item.state, firing, uuid4())

        assert list((await alert_store.firing_severities("web-1")).values()) == ["critical"]
        assert await alert_store.firing_severities("web-2") == {}
        [other] = await alert_store.rules_to_evaluate(["web-2"])
        assert other.state.version is None

    @pytest.mark.asyncio
    async def test_one_rule_per_metric_and_severity_at_each_place(self, postgres):
        await alert_store.create_rule(_rule(threshold=80))
        with pytest.raises(alert_store.DuplicateRule):
            await alert_store.create_rule(_rule(threshold=70))
        # The same metric and severity elsewhere is what overriding means.
        await alert_store.create_rule(_rule(SCOPE_SERVER, server_id="web-1", threshold=70))

    @pytest.mark.asyncio
    async def test_the_database_refuses_an_incoherent_place(self, postgres):
        with pytest.raises(Exception, match="alert_rules_scope_check"):
            async with db.session() as s:
                await s.execute(text(
                    "INSERT INTO alert_rules (rule_id, scope, server_id, metric_name, operator, threshold,"
                    " severity, cooldown_minutes) VALUES (gen_random_uuid(), 'global', 'web-1',"
                    " 'cpu_usage_percent', '>=', 90, 'critical', 5)"
                ))

    @pytest.mark.asyncio
    async def test_a_rule_for_an_unknown_group_is_refused(self, postgres):
        with pytest.raises(alert_store.UnknownGroup):
            await alert_store.create_rule(_rule(SCOPE_GROUP, group_id=999))

    @pytest.mark.asyncio
    async def test_channels_add_up_across_places(self, postgres):
        group_id = await _group()
        await _server("db-1", group_id)
        rule = await alert_store.create_rule(_rule())
        made = {}
        for name, place, rule_id in [
            ("everyone", Place(SCOPE_GLOBAL), None), ("group", Place(SCOPE_GROUP, group_id=group_id), None),
            ("own", Place(SCOPE_SERVER, server_id="db-1"), None),
            ("other_server", Place(SCOPE_SERVER, server_id="web-1"), None),
            ("other_rule", Place(SCOPE_GLOBAL), (await alert_store.create_rule(_rule(severity="warning"))).rule_id),
        ]:
            channel = AlertChannel(
                channel_id=uuid4(), rule_id=rule_id, server_id=place.server_id, channel_type="telegram",
                config={}, created_at=_NOW, scope=place.scope, group_id=place.group_id,
            )
            made[name] = (await alert_store.create_channel(channel)).channel_id

        found = await alert_store.channels_for_alert("db-1", rule.rule_id, group_id)

        assert {ch.channel_id for ch in found} == {made["everyone"], made["group"], made["own"]}


class TestGlobalDefaults:
    @pytest.mark.asyncio
    async def test_per_server_copies_become_one_global_rule_keeping_state_and_channels(self, postgres):
        """What 0.2.0 left: each server with its own five copies, one of them firing."""
        copies = {}
        for server_id in ("web-1", "web-2"):
            copies[server_id] = default_rules(server_id, _NOW)
            for rule in copies[server_id]:
                await alert_store.create_rule(rule)
        async with db.session() as s:
            await s.execute(text("INSERT INTO alert_defaults_applied (server_id) VALUES ('web-1'), ('web-2')"))
        cpu_web1 = next(r for r in copies["web-1"] if r.metric_name == "cpu_usage_percent")
        [item] = [i for i in await alert_store.rules_to_evaluate(["web-1"]) if i.rule.rule_id == cpu_web1.rule_id]
        await alert_store.change_state(
            cpu_web1.rule_id, "web-1", item.state, AlertState(state=STATE_FIRING, last_fired_at=_NOW), uuid4(),
        )
        bound = await alert_store.create_channel(AlertChannel(
            channel_id=uuid4(), rule_id=cpu_web1.rule_id, server_id="web-1", channel_type="telegram",
            config={}, created_at=_NOW,
        ))

        assert await ensure_global_default_rules()

        assert await alert_store.list_rules("web-1") == []
        assert await alert_store.list_rules("web-2") == []
        globals_ = await alert_store.rules_at(Place(SCOPE_GLOBAL))
        assert len(globals_) == 5
        cpu_global = next(r for r in globals_ if r.metric_name == "cpu_usage_percent")
        # Still firing on web-1 under the global rule, so it does not fire again.
        assert await alert_store.firing_severities("web-1") == {str(cpu_global.rule_id): "critical"}
        assert (await alert_store.get_channel_by_id(bound.channel_id)).rule_id == cpu_global.rule_id
        async with db.session() as s:
            actions = set(await s.scalars(select(AuditLogRow.action).where(AuditLogRow.target_table == "alert_rules")))
        assert "alert_rules.adopt_defaults" in actions

    @pytest.mark.asyncio
    async def test_an_edited_copy_stays_as_the_servers_own_rule(self, postgres):
        cpu = next(r for r in default_rules("web-1", _NOW) if r.metric_name == "cpu_usage_percent")
        cpu.threshold = 97
        await alert_store.create_rule(cpu)

        await ensure_global_default_rules()

        assert [r.threshold for r in await alert_store.list_rules("web-1")] == [97]
        winner = next(r for r in await alert_store.effective_rules("web-1") if r.metric_name == "cpu_usage_percent")
        assert winner.rule_id == cpu.rule_id

    @pytest.mark.asyncio
    async def test_a_default_a_server_had_deleted_stays_off_there(self, postgres):
        for rule in default_rules("web-1", _NOW):
            await alert_store.create_rule(rule)
            if rule.metric_name == "memory_usage_percent":
                await alert_store.delete_rule("web-1", rule.rule_id)
        async with db.session() as s:
            await s.execute(text("INSERT INTO alert_defaults_applied (server_id) VALUES ('web-1')"))

        await ensure_global_default_rules()

        metrics_web1 = {r.metric_name for r in await alert_store.effective_rules("web-1")}
        metrics_new = {r.metric_name for r in await alert_store.effective_rules("web-9")}
        assert "memory_usage_percent" not in metrics_web1
        assert "memory_usage_percent" in metrics_new

    @pytest.mark.asyncio
    async def test_runs_once(self, postgres):
        assert await ensure_global_default_rules()
        assert not await ensure_global_default_rules()
        async with db.session() as s:
            assert await s.scalar(select(func.count()).select_from(AlertRuleRow)) == 5
            assert await s.scalar(select(func.count()).select_from(AlertStateRow)) == 0


@pytest.fixture
def client(postgres) -> TestClient:
    app = FastAPI()
    app.include_router(scoped_router)
    act_as(app, role="operator")
    return TestClient(app)


_BODY = {"metric_name": "cpu_usage_percent", "operator": ">=", "threshold": 90, "severity": "critical"}


class TestScopedRoutes:
    def test_create_edit_and_delete_a_global_rule(self, client):
        created = client.post("/alerts/rules", json={**_BODY, "scope": "global"})
        assert created.status_code == 201, created.text
        rule_id = created.json()["rule_id"]
        assert created.json()["scope"] == "global"

        edited = client.patch(f"/alerts/rules/{rule_id}", json={"threshold": 95, "enabled": False})
        assert (edited.json()["threshold"], edited.json()["enabled"]) == (95, False)
        assert [r["rule_id"] for r in client.get("/alerts/rules", params={"scope": "global"}).json()] == [rule_id]
        assert client.delete(f"/alerts/rules/{rule_id}").status_code == 204
        assert client.get("/alerts/rules", params={"scope": "global"}).json() == []

    def test_metric_and_severity_cannot_be_edited(self, client):
        rule_id = client.post("/alerts/rules", json={**_BODY, "scope": "global"}).json()["rule_id"]

        assert client.patch(f"/alerts/rules/{rule_id}", json={"severity": "warning"}).status_code == 422

    def test_an_incoherent_place_is_a_422(self, client):
        assert client.post("/alerts/rules", json={**_BODY, "scope": "global", "server_id": "web-1"}).status_code == 422
        assert client.post("/alerts/rules", json={**_BODY, "scope": "group"}).status_code == 422

    def test_resolved_rules_show_the_winner_and_what_it_overrides(self, client):
        client.post("/alerts/rules", json={**_BODY, "scope": "global", "threshold": 80})
        client.post("/alerts/rules", json={**_BODY, "scope": "server", "server_id": "web-1", "threshold": 95})

        [resolved] = client.get("/alerts/web-1/resolved-rules").json()

        assert (resolved["rule"]["scope"], resolved["rule"]["threshold"]) == ("server", 95)
        assert [r["threshold"] for r in resolved["overrides"]] == [80]

    def test_an_inherited_rule_is_not_deleted_through_the_servers_route(self, client):
        from app.alerts import router as per_server_router

        app = client.app
        app.include_router(per_server_router)
        rule_id = client.post("/alerts/rules", json={**_BODY, "scope": "global"}).json()["rule_id"]

        assert client.delete(f"/alerts/web-1/rules/{rule_id}").status_code == 409
        assert [r["scope"] for r in client.get("/alerts/web-1/rules").json()["rules"]] == ["global"]
