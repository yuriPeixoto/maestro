"""
Tests for the user store (auth_db.py), against the Postgres test database.

The `postgres` fixture (conftest.py) empties the tables before every test.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app import auth_db
from app.config import settings

needs_postgres = pytest.mark.usefixtures("postgres")


@pytest.fixture(autouse=True)
def _no_legacy_admin(monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password_hash", "")


# ── Password validation ──────────────────────────────────────────────────────

class TestValidateNewPassword:
    def test_rejects_short_password(self):
        with pytest.raises(ValueError):
            auth_db.validate_new_password("short")

    def test_accepts_min_length_password(self):
        auth_db.validate_new_password("exactly8")  # must not raise


# ── Hashing ──────────────────────────────────────────────────────────────────

class TestPasswordHashing:
    def test_verify_password_round_trip(self):
        hashed = auth_db._hash("correct horse battery staple")
        assert auth_db.verify_password("correct horse battery staple", hashed)
        assert not auth_db.verify_password("wrong", hashed)


# ── Bootstrap ─────────────────────────────────────────────────────────────────

@needs_postgres
class TestBootstrap:
    @pytest.mark.asyncio
    async def test_no_legacy_settings_seeds_nothing(self):
        await auth_db.bootstrap_legacy_admin()
        assert await auth_db.list_users() == []

    @pytest.mark.asyncio
    async def test_legacy_settings_seed_one_user(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_username", "legacyadmin")
        monkeypatch.setattr(settings, "admin_password_hash", auth_db._hash("legacypass1"))
        await auth_db.bootstrap_legacy_admin()

        user = await auth_db.get_user_by_username("legacyadmin")
        assert user is not None
        assert auth_db.verify_password("legacypass1", user["password_hash"])

    @pytest.mark.asyncio
    async def test_bootstrap_only_runs_on_empty_table(self, monkeypatch):
        await auth_db.create_user("someone", "someone@example.com", "somepassword1")

        monkeypatch.setattr(settings, "admin_username", "legacyadmin")
        monkeypatch.setattr(settings, "admin_password_hash", auth_db._hash("legacypass1"))
        await auth_db.bootstrap_legacy_admin()  # table already has a row — must not seed the legacy user too

        assert await auth_db.get_user_by_username("legacyadmin") is None
        assert len(await auth_db.list_users()) == 1


# ── CRUD ──────────────────────────────────────────────────────────────────────

@needs_postgres
class TestUserCrud:
    @pytest.mark.asyncio
    async def test_create_and_fetch_user(self):
        created = await auth_db.create_user("alice", "alice@example.com", "password123")

        by_username = await auth_db.get_user_by_username("alice")
        by_email = await auth_db.get_user_by_email("alice@example.com")
        by_id = await auth_db.get_user_by_id(created["id"])

        assert by_username["id"] == by_email["id"] == by_id["id"]

    @pytest.mark.asyncio
    async def test_update_email(self):
        created = await auth_db.create_user("bob", "bob@example.com", "password123")
        await auth_db.update_email(created["id"], "bob.new@example.com")

        user = await auth_db.get_user_by_id(created["id"])
        assert user["email"] == "bob.new@example.com"

    @pytest.mark.asyncio
    async def test_update_password_changes_hash(self):
        created = await auth_db.create_user("carol", "carol@example.com", "password123")
        await auth_db.update_password(created["id"], "newpassword456")

        user = await auth_db.get_user_by_id(created["id"])
        assert auth_db.verify_password("newpassword456", user["password_hash"])
        assert not auth_db.verify_password("password123", user["password_hash"])

    @pytest.mark.asyncio
    async def test_delete_user(self):
        created = await auth_db.create_user("dave", "dave@example.com", "password123")
        await auth_db.delete_user(created["id"])

        assert await auth_db.get_user_by_id(created["id"]) is None


    @pytest.mark.asyncio
    async def test_duplicate_username_is_refused_by_the_database(self):
        await auth_db.create_user("gina", "gina@example.com", "password123")

        with pytest.raises(Exception, match="users_username_key"):
            await auth_db.create_user("gina", "other@example.com", "password123")

    @pytest.mark.asyncio
    async def test_list_gives_dates_as_text(self):
        await auth_db.create_user("hugo", "hugo@example.com", "password123")

        (row,) = await auth_db.list_users()

        assert set(row) == {"id", "username", "email", "created_at", "updated_at"}
        assert row["created_at"].endswith("+00:00")


# ── Login lockout ─────────────────────────────────────────────────────────────

@needs_postgres
class TestLockout:
    async def _fail(self, user_id: int, times: int) -> dict:
        for _ in range(times):
            await auth_db.record_login_failure(user_id)
        return await auth_db.get_user_by_id(user_id)

    @pytest.mark.asyncio
    async def test_the_limit_locks_the_account_for_one_window(self):
        created = await auth_db.create_user("ivo", "ivo@example.com", "password123")

        before = await self._fail(created["id"], auth_db.MAX_LOGIN_FAILURES - 1)
        after = await self._fail(created["id"], 1)

        assert auth_db.seconds_locked(before) == 0
        window = auth_db.LOGIN_FAILURE_WINDOW.total_seconds()
        assert window - 5 <= auth_db.seconds_locked(after) <= window

    @pytest.mark.asyncio
    async def test_failures_older_than_the_window_start_over(self, monkeypatch):
        created = await auth_db.create_user("jade", "jade@example.com", "password123")
        await self._fail(created["id"], auth_db.MAX_LOGIN_FAILURES - 1)

        later = auth_db._now() + auth_db.LOGIN_FAILURE_WINDOW + timedelta(seconds=1)
        monkeypatch.setattr(auth_db, "_now", lambda: later)
        user = await self._fail(created["id"], 1)

        assert user["failed_login_count"] == 1
        assert auth_db.seconds_locked(user) == 0

    @pytest.mark.asyncio
    async def test_the_lock_expires(self, monkeypatch):
        created = await auth_db.create_user("kai", "kai@example.com", "password123")
        user = await self._fail(created["id"], auth_db.MAX_LOGIN_FAILURES)

        later = auth_db._now() + auth_db.LOGIN_FAILURE_WINDOW
        monkeypatch.setattr(auth_db, "_now", lambda: later)

        assert auth_db.seconds_locked(user) == 0

    @pytest.mark.asyncio
    async def test_clearing_unlocks(self):
        created = await auth_db.create_user("lia", "lia@example.com", "password123")
        await self._fail(created["id"], auth_db.MAX_LOGIN_FAILURES)

        await auth_db.clear_login_failures(created["id"])
        user = await auth_db.get_user_by_id(created["id"])

        assert (user["failed_login_count"], user["locked_until"]) == (0, None)


# ── Password reset tokens ─────────────────────────────────────────────────────

@needs_postgres
class TestResetTokens:
    @pytest.mark.asyncio
    async def test_valid_token_resolves_to_user_and_is_single_use(self):
        created = await auth_db.create_user("erin", "erin@example.com", "password123")
        token = await auth_db.create_reset_token(created["id"])

        assert await auth_db.consume_reset_token(token) == created["id"]
        # Second consumption of the same token must fail — single use.
        assert await auth_db.consume_reset_token(token) is None

    @pytest.mark.asyncio
    async def test_unknown_token_returns_none(self):
        assert await auth_db.consume_reset_token("not-a-real-token") is None

    @pytest.mark.asyncio
    async def test_expired_token_returns_none(self, monkeypatch):
        created = await auth_db.create_user("frank", "frank@example.com", "password123")
        monkeypatch.setattr(settings, "password_reset_token_expire_minutes", -1)  # already expired
        token = await auth_db.create_reset_token(created["id"])

        assert await auth_db.consume_reset_token(token) is None
