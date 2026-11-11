"""
Accounts managed by admins (edit, deactivate, temporary password) and the audit log,
end to end with real tokens against the Postgres test database.
"""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from app import audit, auth_db, db, login_throttle
from app.alerts import router as alerts_router
from app.audit_routes import router as audit_router
from app.auth import client_ip, require_active_user
from app.auth import router as auth_router
from app.config import settings
from app.permissions import ROLE_PERMISSIONS, Permission, Role
from app.users import router as users_router

PASSWORD = "password-123"

needs_postgres = pytest.mark.usefixtures("postgres")


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password_hash", "")
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-" + "0" * 32)
    login_throttle._failures.clear()
    audit.current_actor.set(None)


@pytest.fixture
def client(postgres) -> TestClient:
    protected = [Depends(require_active_user)]
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(users_router, dependencies=protected)
    app.include_router(audit_router, dependencies=protected)
    app.include_router(alerts_router, dependencies=protected)
    return TestClient(app, raise_server_exceptions=False)


async def _account(username: str, role: Role = Role.ADMIN, must_change: bool = False) -> int:
    created = await auth_db.create_user(
        username, f"{username}@example.com", PASSWORD, must_change_password=must_change, role=role,
    )
    return created["id"]


def _login(client: TestClient, username: str, password: str = PASSWORD):
    return client.post("/auth/login", json={"username": username, "password": password})


def _bearer(client: TestClient, username: str, password: str = PASSWORD) -> dict:
    response = _login(client, username, password)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _audit(client: TestClient, headers: dict, **filters) -> list[dict]:
    response = client.get("/audit", headers=headers, params=filters)
    assert response.status_code == 200, response.text
    return response.json()["entries"]


# ── Me ───────────────────────────────────────────────────────────────────────

@needs_postgres
class TestMe:
    @pytest.mark.asyncio
    async def test_me_carries_the_role_and_its_permissions(self, client):
        await _account("olga", Role.OPERATOR)

        me = client.get("/auth/me", headers=_bearer(client, "olga")).json()

        assert me["role"] == "operator"
        assert Permission.MANAGE_ALERTS in me["permissions"]
        assert Permission.MANAGE_USERS not in me["permissions"]

    @pytest.mark.asyncio
    async def test_own_full_name_can_be_edited(self, client):
        await _account("pia", Role.VIEWER)
        headers = _bearer(client, "pia")

        assert client.patch("/auth/me", headers=headers, json={"full_name": " Pia Lima "}).status_code == 200
        assert client.get("/auth/me", headers=headers).json()["full_name"] == "Pia Lima"


# ── Managing accounts ────────────────────────────────────────────────────────

@needs_postgres
class TestManageUsers:
    @pytest.mark.asyncio
    async def test_create_without_password_returns_a_generated_one_once(self, client):
        await _account("ana")
        headers = _bearer(client, "ana")

        created = client.post("/users", headers=headers, json={"username": "bia", "email": "bia@example.com"})

        assert created.status_code == 201
        body = created.json()
        assert body["role"] == "viewer" and body["must_change_password"] is True
        assert len(body["temporary_password"]) == auth_db.TEMPORARY_PASSWORD_LENGTH
        assert _login(client, "bia", body["temporary_password"]).json()["must_change_password"] is True
        listed = {u["username"]: u for u in client.get("/users", headers=headers).json()}
        assert "temporary_password" not in listed["bia"]

    @pytest.mark.asyncio
    async def test_edit_name_email_and_role(self, client):
        await _account("ana")
        target = await _account("caio", Role.VIEWER)
        headers = _bearer(client, "ana")

        response = client.patch(
            f"/users/{target}", headers=headers,
            json={"full_name": "Caio Reis", "email": "caio.reis@example.com", "role": "operator"},
        )

        assert response.status_code == 200
        assert (response.json()["full_name"], response.json()["role"]) == ("Caio Reis", "operator")

    @pytest.mark.asyncio
    async def test_email_of_another_account_is_a_conflict(self, client):
        await _account("ana")
        target = await _account("caio", Role.VIEWER)

        response = client.patch(f"/users/{target}", headers=_bearer(client, "ana"), json={"email": "ana@example.com"})

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_a_role_change_applies_to_open_sessions(self, client):
        await _account("ana")
        target = await _account("dora", Role.OPERATOR)
        dora = _bearer(client, "dora")
        rule = {"metric_name": "cpu_usage_percent", "operator": ">=", "threshold": 90, "severity": "critical"}
        assert client.post("/alerts/web-1/rules", headers=dora, json=rule).status_code != 403

        client.patch(f"/users/{target}", headers=_bearer(client, "ana"), json={"role": "viewer"})

        assert client.post("/alerts/web-1/rules", headers=dora, json=rule).status_code == 403

    @pytest.mark.asyncio
    async def test_no_changing_your_own_role_or_deactivating_yourself(self, client):
        admin = await _account("ana")
        headers = _bearer(client, "ana")

        assert client.patch(f"/users/{admin}", headers=headers, json={"role": "viewer"}).status_code == 400
        assert client.post(f"/users/{admin}/deactivate", headers=headers).status_code == 400
        # Same role is not a change.
        assert client.patch(f"/users/{admin}", headers=headers, json={"role": "admin"}).status_code == 200

    @pytest.mark.asyncio
    async def test_unknown_account_is_404(self, client):
        await _account("ana")
        headers = _bearer(client, "ana")

        assert client.patch("/users/9999", headers=headers, json={"role": "viewer"}).status_code == 404
        assert client.post("/users/9999/deactivate", headers=headers).status_code == 404
        assert client.post("/users/9999/temporary-password", headers=headers).status_code == 404

    @pytest.mark.asyncio
    async def test_deactivated_account_cannot_log_in_and_its_sessions_end(self, client):
        await _account("ana")
        target = await _account("eva", Role.VIEWER)
        eva = _bearer(client, "eva")

        response = client.post(f"/users/{target}/deactivate", headers=_bearer(client, "ana"))

        assert response.status_code == 200 and response.json()["active"] is False
        assert client.get("/auth/me", headers=eva).status_code == 401
        assert _login(client, "eva").status_code == 401
        assert _login(client, "eva").json()["detail"] == _login(client, "nobody").json()["detail"]

    @pytest.mark.asyncio
    async def test_a_reactivated_account_logs_in_again_but_old_sessions_stay_closed(self, client):
        await _account("ana")
        target = await _account("eva", Role.VIEWER)
        eva = _bearer(client, "eva")
        admin = _bearer(client, "ana")
        client.post(f"/users/{target}/deactivate", headers=admin)

        assert client.post(f"/users/{target}/reactivate", headers=admin).json()["active"] is True
        assert client.get("/auth/me", headers=eva).status_code == 401
        assert _login(client, "eva").status_code == 200

    @pytest.mark.asyncio
    async def test_the_roles_matrix_is_the_one_the_api_enforces(self, client):
        await _account("ana")
        await _account("olga", Role.OPERATOR)

        body = client.get("/users/roles", headers=_bearer(client, "ana")).json()

        assert body["permissions"] == [p.value for p in Permission]
        by_role = {r["role"]: set(r["permissions"]) for r in body["roles"]}
        assert by_role == {role.value: {p.value for p in granted} for role, granted in ROLE_PERMISSIONS.items()}
        assert client.get("/users/roles", headers=_bearer(client, "olga")).status_code == 403

    @pytest.mark.asyncio
    async def test_last_access_is_recorded(self, client):
        await _account("ana")
        target = await _account("fabio", Role.VIEWER)
        _bearer(client, "fabio")

        listed = {u["id"]: u for u in client.get("/users", headers=_bearer(client, "ana")).json()}

        assert listed[target]["last_login_at"] is not None
        assert listed[target]["last_seen_at"] is not None


@needs_postgres
class TestLastAdmin:
    """Through the API the caller is an active admin too, so this guards the race of two
    admins demoting each other at once; auth_db is where it is enforced."""

    @pytest.mark.asyncio
    async def test_demoting_the_only_active_admin_is_refused(self):
        admin = await _account("ana")

        with pytest.raises(auth_db.LastAdminError):
            await auth_db.update_user(admin, role=Role.OPERATOR)
        with pytest.raises(auth_db.LastAdminError):
            await auth_db.deactivate_user(admin)
        assert (await auth_db.get_user_by_id(admin))["role"] == "admin"

    @pytest.mark.asyncio
    async def test_with_another_active_admin_it_is_allowed(self):
        first = await _account("ana")
        await _account("beto")

        await auth_db.update_user(first, role=Role.OPERATOR)

        assert (await auth_db.get_user_by_id(first))["role"] == "operator"

    @pytest.mark.asyncio
    async def test_a_deactivated_admin_does_not_count(self):
        first = await _account("ana")
        second = await _account("beto")
        await auth_db.deactivate_user(second)

        with pytest.raises(auth_db.LastAdminError):
            await auth_db.update_user(first, role=Role.VIEWER)

    @pytest.mark.asyncio
    async def test_the_api_answers_409(self, client, monkeypatch):
        await _account("ana")
        target = await _account("beto")

        async def refuse(*_args, **_kwargs):
            raise auth_db.LastAdminError

        monkeypatch.setattr(auth_db, "deactivate_user", refuse)
        response = client.post(f"/users/{target}/deactivate", headers=_bearer(client, "ana"))

        assert response.status_code == 409


# ── Temporary password (#99) ─────────────────────────────────────────────────

@needs_postgres
class TestTemporaryPassword:
    @pytest.mark.asyncio
    async def test_forgotten_password_flow(self, client):
        await _account("ana")
        target = await _account("gil", Role.OPERATOR)
        old_session = _bearer(client, "gil")
        for _ in range(auth_db.MAX_LOGIN_FAILURES):
            _login(client, "gil", "wrong-password")
        assert _login(client, "gil").status_code == 429

        response = client.post(f"/users/{target}/temporary-password", headers=_bearer(client, "ana"))

        assert response.status_code == 200
        temporary = response.json()["temporary_password"]
        assert len(temporary) == auth_db.TEMPORARY_PASSWORD_LENGTH
        assert set(temporary) <= set(auth_db.TEMPORARY_PASSWORD_ALPHABET)
        # Open sessions end, the lockout is gone, and the old password no longer works.
        assert client.get("/auth/me", headers=old_session).status_code == 401
        assert _login(client, "gil").status_code == 401
        login = _login(client, "gil", temporary)
        assert login.status_code == 200 and login.json()["must_change_password"] is True
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get("/auth/me", headers=headers).status_code == 200
        changed = client.post(
            "/auth/change-password", headers=headers,
            json={"current_password": temporary, "new_password": "gil-own-password"},
        )
        assert changed.status_code == 200
        assert _login(client, "gil", "gil-own-password").json()["must_change_password"] is False

    @pytest.mark.asyncio
    async def test_each_call_gives_a_different_password(self, client):
        await _account("ana")
        target = await _account("gil", Role.VIEWER)
        headers = _bearer(client, "ana")

        first = client.post(f"/users/{target}/temporary-password", headers=headers).json()["temporary_password"]
        second = client.post(f"/users/{target}/temporary-password", headers=headers).json()["temporary_password"]

        assert first != second

    @pytest.mark.asyncio
    async def test_not_for_your_own_account(self, client):
        admin = await _account("ana")

        assert client.post(f"/users/{admin}/temporary-password", headers=_bearer(client, "ana")).status_code == 400

    @pytest.mark.asyncio
    async def test_not_for_a_deactivated_account(self, client):
        await _account("ana")
        target = await _account("gil", Role.VIEWER)
        headers = _bearer(client, "ana")
        client.post(f"/users/{target}/deactivate", headers=headers)

        assert client.post(f"/users/{target}/temporary-password", headers=headers).status_code == 409

    @pytest.mark.asyncio
    async def test_operators_cannot_do_it(self, client):
        target = await _account("gil", Role.VIEWER)
        await _account("olga", Role.OPERATOR)

        response = client.post(f"/users/{target}/temporary-password", headers=_bearer(client, "olga"))

        assert response.status_code == 403


# ── Audit log ────────────────────────────────────────────────────────────────

@needs_postgres
class TestAuditLog:
    @pytest.mark.asyncio
    async def test_changes_through_the_api_name_who_and_from_where(self, client):
        await _account("ana")
        target = await _account("hana", Role.VIEWER)
        headers = {**_bearer(client, "ana"), "User-Agent": "audit-test"}

        client.patch(f"/users/{target}", headers=headers, json={"role": "operator"})
        client.post(f"/users/{target}/temporary-password", headers=headers)

        entries = _audit(client, headers, target_table="users", target_id=str(target))
        by_action = {e["action"]: e for e in entries}
        update = by_action["users.update"]
        assert (update["actor"], update["user_agent"]) == ("ana", "audit-test")
        assert (update["before"]["role"], update["after"]["role"]) == ("viewer", "operator")
        reset = by_action["users.temporary_password"]
        assert reset["after"]["password_hash"] == "[changed]"
        assert reset["after"]["must_change_password"] is True

    @pytest.mark.asyncio
    async def test_no_password_ever_reaches_the_log(self, client):
        await _account("ana")
        target = await _account("ivo", Role.VIEWER)
        headers = _bearer(client, "ana")

        temporary = client.post(f"/users/{target}/temporary-password", headers=headers).json()["temporary_password"]
        created = client.post("/users", headers=headers, json={"username": "jo", "email": "jo@example.com"}).json()

        dump = str(_audit(client, headers, limit=200))
        assert temporary not in dump and created["temporary_password"] not in dump
        assert "$2b$" not in dump  # no bcrypt hash either

    @pytest.mark.asyncio
    async def test_logins_and_failures_are_recorded(self, client):
        await _account("ana")
        await _account("kim", Role.VIEWER)
        _login(client, "kim", "wrong-password")
        _bearer(client, "kim")

        actions = [e["action"] for e in _audit(client, _bearer(client, "ana"), action="auth.")]

        assert "auth.login_failed" in actions and actions.count("auth.login") >= 2

    @pytest.mark.asyncio
    async def test_the_failure_that_locks_the_account_says_so(self, client):
        await _account("ana")
        target = await _account("kim", Role.VIEWER)
        for _ in range(auth_db.MAX_LOGIN_FAILURES):
            _login(client, "kim", "wrong-password")

        failures = _audit(client, _bearer(client, "ana"), action="auth.login_failed", target_id=str(target))

        assert [f["after"].get("locked", False) for f in failures] == [True] + [False] * (auth_db.MAX_LOGIN_FAILURES - 1)

    @pytest.mark.asyncio
    async def test_a_change_made_straight_in_the_database_is_recorded(self, postgres, client):
        await _account("ana")
        target = await _account("lu", Role.VIEWER)
        engine = create_async_engine(
            db.async_url(postgres), poolclass=NullPool,
            connect_args={"server_settings": {"application_name": "DBeaver 25.2"}},
        )
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE users SET role = 'admin' WHERE id = :id"), {"id": target})
        await engine.dispose()

        [entry] = _audit(client, _bearer(client, "ana"), action="users.update")

        assert entry["actor_user_id"] is None
        assert entry["actor"].endswith(" via DBeaver 25.2")
        assert entry["after"]["role"] == "admin"

    @pytest.mark.asyncio
    async def test_bookkeeping_columns_alone_write_nothing(self, client):
        target = await _account("mia", Role.VIEWER)
        await auth_db.record_login_failure(target)
        await auth_db.clear_login_failures(target)
        await auth_db.mark_release_seen(target, "0.1.0")
        await auth_db.record_login(target)

        async with db.session() as s:
            count = await s.scalar(text("SELECT count(*) FROM audit_log WHERE action = 'users.update'"))

        assert count == 0

    @pytest.mark.asyncio
    async def test_rule_changes_are_recorded_with_their_own_action(self, client):
        await _account("ana")
        headers = _bearer(client, "ana")
        rule = {"metric_name": "cpu_usage_percent", "operator": ">=", "threshold": 90, "severity": "critical"}
        created = client.post("/alerts/web-1/rules", headers=headers, json=rule)
        assert created.status_code == 201, created.text
        client.delete(f"/alerts/web-1/rules/{created.json()['rule_id']}", headers=headers)

        actions = [e["action"] for e in _audit(client, headers, target_table="alert_rules")]

        assert actions == ["alert_rules.delete", "alert_rules.insert"]

    @pytest.mark.asyncio
    async def test_each_entry_says_what_its_target_is(self, client):
        await _account("ana")
        target = await _account("rui", Role.VIEWER)
        headers = _bearer(client, "ana")
        client.patch(f"/users/{target}", headers=headers, json={"full_name": "Rui Prado"})
        rule = {"metric_name": "cpu_usage_percent", "operator": ">=", "threshold": 85, "severity": "warning"}
        rule_id = client.post("/alerts/web-1/rules", headers=headers, json=rule).json()["rule_id"]
        client.delete(f"/alerts/web-1/rules/{rule_id}", headers=headers)

        [account] = _audit(client, headers, action="users.update", target_id=str(target))
        [deleted_rule] = _audit(client, headers, action="alert_rules.delete")

        assert account["target_info"] == {"kind": "user", "username": "rui", "full_name": "Rui Prado"}
        assert deleted_rule["target_info"] == {
            "kind": "rule", "scope": "server", "server_id": "web-1", "group_id": None, "metric_name": "cpu_usage_percent",
            "operator": ">=", "threshold": 85, "deleted": True,
        }

    @pytest.mark.asyncio
    async def test_each_entry_describes_the_target_as_it_was_then(self, client):
        await _account("ana")
        headers = _bearer(client, "ana")
        rule = {"metric_name": "cpu_usage_percent", "operator": ">=", "threshold": 1, "severity": "critical"}
        rule_id = client.post("/alerts/web-1/rules", headers=headers, json=rule).json()["rule_id"]
        async with db.session() as s:
            await s.execute(text("UPDATE alert_rules SET threshold = 99 WHERE rule_id = :id"), {"id": rule_id})
        client.delete(f"/alerts/web-1/rules/{rule_id}", headers=headers)

        described = {e["action"]: e["target_info"] for e in _audit(client, headers, target_id=rule_id)}

        assert described["alert_rules.insert"]["threshold"] == 1
        assert described["alert_rules.update"]["threshold"] == 99
        assert described["alert_rules.delete"]["threshold"] == 99
        # Removed since: every line says so, whatever it was then.
        assert {info["deleted"] for info in described.values()} == {True}

    @pytest.mark.asyncio
    async def test_outside_keeps_only_changes_no_account_made(self, postgres, client):
        await _account("ana")
        target = await _account("sol", Role.VIEWER)
        headers = _bearer(client, "ana")
        _login(client, "sol", "wrong-password")
        client.patch(f"/users/{target}", headers=headers, json={"full_name": "Sol"})
        engine = create_async_engine(
            db.async_url(postgres), poolclass=NullPool,
            connect_args={"server_settings": {"application_name": "DBeaver 25.2"}},
        )
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE users SET email = 'sol@other.example' WHERE id = :id"), {"id": target})
        await engine.dispose()

        entries = _audit(client, headers, outside="true")

        # Account creation in the fixture ran with no caller either: it is outside too.
        assert {e["actor_user_id"] for e in entries} == {None}
        assert "auth.login_failed" not in {e["action"] for e in entries}
        assert any(e["actor"].endswith(" via DBeaver 25.2") for e in entries)

    @pytest.mark.asyncio
    async def test_pages_follow_each_other_newest_first(self, client):
        await _account("ana")
        headers = _bearer(client, "ana")
        for _ in range(5):  # six logins in all
            _bearer(client, "ana")

        first = client.get("/audit", headers=headers, params={"action": "auth.login", "limit": 3}).json()
        second = client.get(
            "/audit", headers=headers,
            params={"action": "auth.login", "limit": 3, "before_id": first["next_before_id"]},
        ).json()

        ids = [e["id"] for e in first["entries"] + second["entries"]]
        assert len(ids) == 6 and ids == sorted(ids, reverse=True)
        assert second["next_before_id"] is None


class TestTargetAsItWas:
    """Pure: the entry's own row, laid over the description of now."""

    _USER_NOW = {"kind": "user", "username": "rui", "full_name": "Rui Prado"}

    def test_an_event_that_copied_no_row_keeps_the_description_of_now(self):
        entry = {"target_table": "users", "after": {"reason": "bad_password"}, "before": None}

        assert audit.target_as_it_was(entry, self._USER_NOW) == self._USER_NOW

    def test_a_delete_is_described_by_the_row_before_it(self):
        entry = {"target_table": "users", "after": None, "before": {"username": "rui", "full_name": "Rui"}}

        assert audit.target_as_it_was(entry, self._USER_NOW)["full_name"] == "Rui"

    def test_a_maintenance_window_says_whether_it_was_weekly_then(self):
        now = {"kind": "maintenance", "server_id": "web-1", "reason": "backup", "weekly": True, "deleted": False}
        entry = {
            "target_table": "maintenance_windows", "before": None,
            "after": {"server_id": "web-1", "reason": "upgrade", "weekdays": None},
        }

        assert audit.target_as_it_was(entry, now) == {**now, "reason": "upgrade", "weekly": False}

    def test_a_target_that_is_gone_stays_undescribed(self):
        entry = {"target_table": "users", "after": {"username": "rui", "full_name": "Rui"}, "before": None}

        assert audit.target_as_it_was(entry, None) is None


@needs_postgres
class TestTheWorker:
    @pytest.mark.asyncio
    async def test_what_the_worker_does_is_signed_as_maestro(self, client):
        from app.default_rules import ensure_global_default_rules

        await _account("ana")
        headers = _bearer(client, "ana")
        token = audit.current_actor.set(audit.WORKER_ACTOR)
        try:
            assert await ensure_global_default_rules()
        finally:
            audit.current_actor.reset(token)

        adopted = _audit(client, headers, action="alert_rules.adopt_defaults")
        assert adopted and {(e["actor"], e["actor_user_id"]) for e in adopted} == {("maestro-worker", None)}
        assert {e["actor"] for e in _audit(client, headers, by_worker="true")} == {"maestro-worker"}
        assert "maestro-worker" not in {e["actor"] for e in _audit(client, headers, outside="true")}

    def test_the_worker_signs_before_its_tasks_start(self, monkeypatch):
        import contextvars

        from app import worker

        monkeypatch.setattr(db, "_application_name", "maestro-api")

        def signed() -> dict[str, str]:
            worker.sign_as_worker()
            return audit.session_settings(None)

        assert contextvars.copy_context().run(signed)["maestro.actor"] == "maestro-worker"
        assert db._application_name == "maestro-worker"


# ── Where a request came from ────────────────────────────────────────────────

def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


class TestClientIp:
    def test_forwarded_for_counts_only_from_the_proxy(self):
        assert client_ip(_request("127.0.0.1", "10.0.0.5")) == "10.0.0.5"
        assert client_ip(_request("192.0.2.9", "10.0.0.5")) == "192.0.2.9"

    def test_the_last_forwarded_entry_is_the_one_the_proxy_added(self):
        assert client_ip(_request("127.0.0.1", "203.0.113.1, 10.0.0.5")) == "10.0.0.5"

    def test_something_that_is_not_an_address_is_dropped(self):
        assert client_ip(_request("testclient")) is None
        assert client_ip(_request("127.0.0.1", "garbage")) == "127.0.0.1"


@needs_postgres
class TestAppendOnly:
    @pytest.mark.asyncio
    async def test_entries_cannot_be_changed_or_removed(self, client):
        await _account("ana")
        _bearer(client, "ana")

        for statement in ("UPDATE audit_log SET actor = 'someone else'", "DELETE FROM audit_log"):
            with pytest.raises(Exception, match="append-only"):
                async with db.session() as s:
                    await s.execute(text(statement))

    @pytest.mark.asyncio
    async def test_an_account_with_history_cannot_be_deleted(self, client):
        target = await _account("ana")
        _bearer(client, "ana")

        with pytest.raises(Exception, match="audit_log"):
            async with db.session() as s:
                await s.execute(text("DELETE FROM users WHERE id = :id"), {"id": target})


# ── Changes made outside the API ─────────────────────────────────────────────

_OUTSIDER = "maestro_test_outsider"
_OUTSIDER_PASSWORD = "outsider-local-only"


async def _outsider_engine(url: str, application_name: str = "HeidiSQL"):
    """A second database login, like a person in a database client: not the API's user."""
    engine = create_async_engine(db.async_url(url), poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text(f"""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{_OUTSIDER}') THEN
                    CREATE ROLE {_OUTSIDER} LOGIN PASSWORD '{_OUTSIDER_PASSWORD}';
                END IF;
            END $$"""))
        await conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA public TO {_OUTSIDER}"))
        await conn.execute(text(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {_OUTSIDER}"))
    await engine.dispose()
    outsider_url = make_url(url).set(username=_OUTSIDER, password=_OUTSIDER_PASSWORD).render_as_string(hide_password=False)
    return create_async_engine(
        db.async_url(outsider_url), poolclass=NullPool,
        connect_args={"server_settings": {"application_name": application_name}},
    )


@needs_postgres
class TestOutsideTheApi:
    @pytest.mark.asyncio
    async def test_another_login_cannot_claim_to_be_someone(self, postgres, client):
        await _account("ana")
        target = await _account("nina", Role.VIEWER)
        engine = await _outsider_engine(postgres)
        async with engine.begin() as conn:
            await conn.execute(text("SELECT set_config('maestro.actor', 'ana', true), set_config('maestro.actor_id', '1', true)"))
            await conn.execute(text("UPDATE users SET role = 'admin' WHERE id = :id"), {"id": target})
        await engine.dispose()

        [entry] = _audit(client, _bearer(client, "ana"), action="users.update")

        assert entry["actor"] == f"{_OUTSIDER} via HeidiSQL"
        assert entry["actor_user_id"] is None
        # The address the connection came from, since there is no API request to read it from.
        assert entry["source_ip"] is not None

    @pytest.mark.asyncio
    async def test_another_login_cannot_sign_as_the_worker(self, postgres, client):
        await _account("ana")
        target = await _account("nina", Role.VIEWER)
        engine = await _outsider_engine(postgres, application_name="maestro-worker")
        async with engine.begin() as conn:
            await conn.execute(text("SELECT set_config('maestro.actor', 'maestro-worker', true)"))
            await conn.execute(text("UPDATE users SET role = 'admin' WHERE id = :id"), {"id": target})
        await engine.dispose()
        headers = _bearer(client, "ana")

        [entry] = _audit(client, headers, action="users.update")

        assert entry["actor"] == f"{_OUTSIDER} via maestro-worker"
        assert entry["id"] in {e["id"] for e in _audit(client, headers, outside="true")}
        assert _audit(client, headers, by_worker="true") == []

    @pytest.mark.asyncio
    async def test_truncate_is_recorded(self, postgres, client):
        await _account("ana")
        headers = _bearer(client, "ana")
        rule = {"metric_name": "cpu_usage_percent", "operator": ">=", "threshold": 90, "severity": "critical"}
        client.post("/alerts/web-1/rules", headers=headers, json=rule)
        engine = await _outsider_engine(postgres)
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE alert_rules CASCADE"))
        await engine.dispose()

        entries = _audit(client, headers, action="alert_rules.truncate")

        assert entries and entries[0]["actor"] == f"{_OUTSIDER} via HeidiSQL"
        assert entries[0]["after"] == {"rows": 1}

    @pytest.mark.asyncio
    async def test_the_log_itself_cannot_be_truncated(self, postgres, client):
        await _account("ana")
        _bearer(client, "ana")
        engine = await _outsider_engine(postgres)

        with pytest.raises(Exception, match="append-only"):
            async with engine.begin() as conn:
                await conn.execute(text("TRUNCATE audit_log CASCADE"))
        await engine.dispose()
