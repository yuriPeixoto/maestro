"""
Route-level tests for login, forced password change and login throttling.

A minimal app mounts only the auth/users routers (the real app's lifespan needs
ClickHouse and Redis), backed by a fresh temp SQLite file per test.
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import auth_db, login_throttle
from app.auth import require_active_user
from app.auth import router as auth_router
from app.config import settings
from app.seed_users import seed
from app.users import router as users_router

TEMP_PASSWORD = "temporary1"
NEW_PASSWORD = "my-own-password"


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "auth_db_path", str(tmp_path / "test_auth.db"))
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password_hash", "")
    login_throttle._failures.clear()


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(users_router, dependencies=[Depends(require_active_user)])
    return TestClient(app)


async def _create(username: str, must_change: bool, password: str = TEMP_PASSWORD) -> None:
    await auth_db.init_db()
    await auth_db.create_user(username, f"{username}@example.com", password, must_change_password=must_change)


def _login(client: TestClient, identifier: str, password: str = TEMP_PASSWORD):
    return client.post("/auth/login", json={"username": identifier, "password": password})


def _bearer(client: TestClient, identifier: str, password: str = TEMP_PASSWORD) -> dict:
    return {"Authorization": f"Bearer {_login(client, identifier, password).json()['access_token']}"}


# ── Login ────────────────────────────────────────────────────────────────────

class TestLogin:
    @pytest.mark.asyncio
    async def test_login_by_email_returns_the_username(self, client):
        await _create("alice", must_change=False)

        resp = _login(client, "alice@example.com")

        assert resp.status_code == 200
        assert resp.json()["username"] == "alice"
        assert resp.json()["must_change_password"] is False

    @pytest.mark.asyncio
    async def test_login_reports_pending_password_change(self, client):
        await _create("bob", must_change=True)

        assert _login(client, "bob").json()["must_change_password"] is True


# ── Forced password change ───────────────────────────────────────────────────

class TestForcedPasswordChange:
    @pytest.mark.asyncio
    async def test_everything_but_the_own_account_is_blocked(self, client):
        await _create("carol", must_change=True)
        headers = _bearer(client, "carol")

        assert client.get("/users", headers=headers).status_code == 403
        assert client.patch("/auth/me", headers=headers, json={"email": "x@example.com"}).status_code == 403
        assert client.get("/auth/me", headers=headers).json()["must_change_password"] is True

    @pytest.mark.asyncio
    async def test_changing_the_password_unlocks_the_account(self, client):
        await _create("dave", must_change=True)
        headers = _bearer(client, "dave")

        resp = client.post(
            "/auth/change-password",
            headers=headers,
            json={"current_password": TEMP_PASSWORD, "new_password": NEW_PASSWORD},
        )

        assert resp.status_code == 200
        assert client.get("/users", headers=headers).status_code == 200
        assert _login(client, "dave", NEW_PASSWORD).json()["must_change_password"] is False

    @pytest.mark.asyncio
    async def test_new_password_must_differ_from_the_temporary_one(self, client):
        await _create("erin", must_change=True)

        resp = client.post(
            "/auth/change-password",
            headers=_bearer(client, "erin"),
            json={"current_password": TEMP_PASSWORD, "new_password": TEMP_PASSWORD},
        )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_wrong_current_password_is_not_an_auth_failure(self, client):
        await _create("frank", must_change=False)

        resp = client.post(
            "/auth/change-password",
            headers=_bearer(client, "frank"),
            json={"current_password": "not-the-password", "new_password": NEW_PASSWORD},
        )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_account_created_by_another_user_must_change_password(self, client):
        await _create("grace", must_change=False)

        client.post(
            "/users",
            headers=_bearer(client, "grace"),
            json={"username": "heidi", "email": "heidi@example.com", "password": TEMP_PASSWORD},
        )

        assert _login(client, "heidi").json()["must_change_password"] is True


# ── Throttling ───────────────────────────────────────────────────────────────

class TestLoginThrottle:
    @pytest.mark.asyncio
    async def test_blocks_after_too_many_failures_even_with_the_right_password(self, client):
        await _create("ivan", must_change=False)
        for _ in range(login_throttle.MAX_FAILURES):
            assert _login(client, "ivan", "wrong-password").status_code == 401

        resp = _login(client, "IVAN ")

        assert resp.status_code == 429
        assert int(resp.headers["Retry-After"]) > 0

    @pytest.mark.asyncio
    async def test_successful_login_clears_previous_failures(self, client):
        await _create("judy", must_change=False)
        for _ in range(login_throttle.MAX_FAILURES - 1):
            _login(client, "judy", "wrong-password")

        assert _login(client, "judy").status_code == 200
        assert login_throttle.seconds_until_allowed("judy") == 0

    def test_failures_expire_after_the_window(self, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(login_throttle.time, "monotonic", lambda: clock[0])
        for _ in range(login_throttle.MAX_FAILURES):
            login_throttle.record_failure("mallory")
        assert login_throttle.seconds_until_allowed("mallory") == login_throttle.WINDOW_SECONDS

        clock[0] += login_throttle.WINDOW_SECONDS

        assert login_throttle.seconds_until_allowed("mallory") == 0


# ── Schema upgrade and seeding ───────────────────────────────────────────────

class TestSchemaUpgrade:
    @pytest.mark.asyncio
    async def test_existing_database_gains_the_new_column(self):
        with sqlite3.connect(settings.auth_db_path) as db:
            db.execute(
                "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, "
                "email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TEXT NOT NULL, "
                "updated_at TEXT NOT NULL)"
            )
            db.execute("INSERT INTO users (username, email, password_hash, created_at, updated_at) "
                       "VALUES ('old', 'old@example.com', 'hash', 'now', 'now')")

        await auth_db.init_db()

        assert (await auth_db.get_user_by_username("old"))["must_change_password"] == 0


class TestSeedUsers:
    @pytest.mark.asyncio
    async def test_seed_creates_missing_accounts_and_skips_existing_ones(self, client):
        await _create("kate", must_change=False)
        users = [
            {"username": "kate", "email": "other@example.com"},
            {"username": "leo", "email": "leo@example.com"},
        ]

        report = await seed(users, TEMP_PASSWORD)

        assert [(name, outcome.split(" ")[0]) for name, outcome, _pw in report] == [("kate", "already"), ("leo", "created")]
        assert _login(client, "leo@example.com").json()["must_change_password"] is True
        assert (await auth_db.get_user_by_username("kate"))["must_change_password"] == 0

    @pytest.mark.asyncio
    async def test_seed_without_shared_password_gives_each_account_its_own(self, client):
        users = [{"username": "mia", "email": "mia@example.com"}, {"username": "noah", "email": "noah@example.com"}]

        report = await seed(users, None)

        passwords = [password for _name, _outcome, password in report]
        assert len(set(passwords)) == 2
        assert _login(client, "mia", passwords[0]).status_code == 200
