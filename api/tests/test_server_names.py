"""
Server names: the hostname stays the identity; an admin's shared label shows to everyone
(and beside the hostname in notifications); each account's nickname shows to it alone.
Groups: unique names, and one cannot be deleted while something still uses it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import alert_store, db, server_store
from app.alert_store import AlertRule
from app.clickhouse import AlertEvent
from app.config import settings
from app.notification_text import alert_text, channel_test_text
from app.rule_scope import SCOPE_GROUP
from app.server_directory import router as directory_router
from app.servers import get_redis
from app.servers import router as servers_router
from tests.conftest import act_as

_NOW = datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)


async def _users(*names: str) -> None:
    async with db.session() as s:
        for user_id, name in enumerate(names, start=1):
            await s.execute(text(
                "INSERT INTO users (id, username, email, password_hash) OVERRIDING SYSTEM VALUE"
                " VALUES (:id, :name, :email, 'x')"
            ), {"id": user_id, "name": name, "email": f"{name}@example.com"})


class TestNicknames:
    @pytest.mark.asyncio
    async def test_each_account_sees_only_its_own(self, postgres):
        await _users("ana", "bruno")
        await server_store.register_servers(["app-1"])

        await server_store.set_nickname(1, "app-1", "  Aplicações   principal ")

        mine = await server_store.server_names(1)
        theirs = await server_store.server_names(2)
        assert mine["app-1"].nickname == "Aplicações principal"
        assert theirs["app-1"].nickname is None

    @pytest.mark.asyncio
    async def test_unique_per_account_regardless_of_case(self, postgres):
        await _users("ana", "bruno")
        await server_store.register_servers(["web-1", "web-2"])
        await server_store.set_nickname(1, "web-1", "Main")

        with pytest.raises(server_store.DuplicateName):
            await server_store.set_nickname(1, "web-2", "MAIN")
        await server_store.set_nickname(2, "web-2", "main")  # another account may use it
        await server_store.set_nickname(1, "web-1", "main")  # renaming one's own is fine

    @pytest.mark.asyncio
    async def test_cleared_and_not_audited(self, postgres):
        await _users("ana")
        await server_store.register_servers(["web-1"])
        await server_store.set_nickname(1, "web-1", "Main")

        assert await server_store.clear_nickname(1, "web-1")
        assert not await server_store.clear_nickname(1, "web-1")
        async with db.session() as s:
            logged = await s.scalar(text("SELECT count(*) FROM audit_log WHERE target_table = 'server_nicknames'"))
        assert logged == 0

    @pytest.mark.asyncio
    async def test_an_unknown_server_cannot_get_one(self, postgres):
        await _users("ana")
        with pytest.raises(server_store.UnknownServer):
            await server_store.set_nickname(1, "ghost", "Main")


class TestLabels:
    @pytest.mark.asyncio
    async def test_shared_unique_and_audited(self, postgres):
        await server_store.register_servers(["web-1", "web-2"])
        await server_store.update_server("web-1", label="Aplicações principal")

        with pytest.raises(server_store.DuplicateName):
            await server_store.update_server("web-2", label="aplicações PRINCIPAL")
        assert await server_store.labels(["web-1", "web-2"]) == {"web-1": "Aplicações principal"}
        async with db.session() as s:
            actions = list(await s.scalars(text(
                "SELECT action FROM audit_log WHERE target_table = 'servers' ORDER BY id"
            )))
        assert actions[-1] == "servers.update"

    @pytest.mark.asyncio
    async def test_an_empty_label_clears_it(self, postgres):
        await server_store.register_servers(["web-1"])
        await server_store.update_server("web-1", label="Main")
        await server_store.update_server("web-1", label="   ")

        assert await server_store.labels(["web-1"]) == {}

    def test_notifications_show_the_label_beside_the_hostname(self):
        event = AlertEvent(
            event_id=uuid4(), rule_id=uuid4(), server_id="app-1", metric_name="disk_usage_percent",
            value=96.0, threshold=95.0, severity="critical", state="FIRING", triggered_at=_NOW,
        )

        assert alert_text(event, "Aplicações principal") == (
            "🔴 Crítico em Aplicações principal (app-1): Disco em 96% (limite 95%)"
        )
        assert alert_text(event) == "🔴 Crítico em app-1: Disco em 96% (limite 95%)"
        assert "app-1" in channel_test_text("app-1", "Aplicações principal")
        assert "vários servidores" in channel_test_text(None)


class TestGroups:
    @pytest.mark.asyncio
    async def test_unique_names_and_servers_join_one(self, postgres):
        group = await server_store.create_group("Database", "Postgres hosts")
        with pytest.raises(server_store.DuplicateName):
            await server_store.create_group("database")
        await server_store.register_servers(["db-1"])

        await server_store.update_server("db-1", group_id=group.group_id)

        assert (await server_store.server_names(0))["db-1"].group_name == "Database"
        with pytest.raises(server_store.UnknownGroup):
            await server_store.update_server("db-1", group_id=999)

    @pytest.mark.asyncio
    async def test_a_group_in_use_cannot_be_deleted(self, postgres):
        group = await server_store.create_group("database")
        await server_store.register_servers(["db-1"])
        await server_store.update_server("db-1", group_id=group.group_id)
        rule = await alert_store.create_rule(AlertRule(
            rule_id=uuid4(), server_id=None, metric_name="cpu_usage_percent", operator=">=", threshold=90,
            severity="critical", cooldown_minutes=5, created_at=_NOW, scope=SCOPE_GROUP, group_id=group.group_id,
        ))

        with pytest.raises(server_store.GroupInUse):
            await server_store.delete_group(group.group_id)
        await alert_store.delete_rule_by_id(rule.rule_id)
        await server_store.delete_group(group.group_id)

        assert await server_store.list_groups() == []
        assert (await server_store.server_names(0))["db-1"].group_id is None
        # The name is free again.
        await server_store.create_group("database")


class _Redis:
    def __init__(self, hashes: dict) -> None:
        self.hashes = hashes

    async def hgetall(self, key):
        return self.hashes.get(key, {})

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)


def _app(role: str, user_id: int) -> TestClient:
    app = FastAPI()
    app.include_router(servers_router)
    app.include_router(directory_router)
    act_as(app, role=role, user_id=user_id)
    heartbeat = json.dumps({"last_seen": datetime.now(timezone.utc).isoformat(), "agent_version": "0.3.0"})
    redis = _Redis({settings.heartbeat_state_key: {"web-1": heartbeat}})

    async def fake_redis():
        yield redis

    app.dependency_overrides[get_redis] = fake_redis
    return TestClient(app)


class TestRoutes:
    @pytest.mark.asyncio
    async def test_a_viewer_names_a_server_for_itself_only(self, postgres):
        await _users("admin", "viewer")
        await server_store.register_servers(["web-1"])
        admin, viewer = _app("admin", 1), _app("viewer", 2)

        assert admin.patch("/servers/web-1", json={"label": "Main applications"}).status_code == 204
        assert viewer.patch("/servers/web-1", json={"label": "Mine"}).status_code == 403
        assert viewer.put("/servers/web-1/nickname", json={"nickname": "Big box"}).status_code == 200

        [seen_by_viewer] = viewer.get("/servers").json()
        [seen_by_admin] = admin.get("/servers").json()
        assert (seen_by_viewer["server_id"], seen_by_viewer["label"], seen_by_viewer["nickname"]) == (
            "web-1", "Main applications", "Big box",
        )
        assert seen_by_admin["nickname"] is None
        assert viewer.delete("/servers/web-1/nickname").status_code == 204
        assert viewer.get("/servers/web-1/status").json()["nickname"] is None

    @pytest.mark.asyncio
    async def test_conflicts_and_unknowns(self, postgres):
        await _users("admin")
        await server_store.register_servers(["web-1", "web-2"])
        admin = _app("admin", 1)
        admin.put("/servers/web-1/nickname", json={"nickname": "Main"})

        assert admin.put("/servers/web-2/nickname", json={"nickname": "main"}).status_code == 409
        assert admin.put("/servers/ghost/nickname", json={"nickname": "x"}).status_code == 404
        assert admin.patch("/servers/ghost", json={"label": "x"}).status_code == 404
        group_id = admin.post("/server-groups", json={"name": "web"}).json()["group_id"]
        assert admin.post("/server-groups", json={"name": "WEB"}).status_code == 409
        assert admin.patch("/servers/web-1", json={"group_id": group_id}).status_code == 204
        assert admin.get("/servers").json()[0]["group_name"] == "web"
        assert admin.delete(f"/server-groups/{group_id}").status_code == 204
