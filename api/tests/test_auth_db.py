"""
Unit tests for the SQLite-backed user store (auth_db.py).

Each test points settings.auth_db_path at a fresh temp file so tests never
touch the real dev/prod auth database and don't interfere with each other.
"""
from __future__ import annotations

import pytest

from app import auth_db
from app.config import settings


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_auth.db"
    monkeypatch.setattr(settings, "auth_db_path", str(db_path))
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

class TestBootstrap:
    @pytest.mark.asyncio
    async def test_no_legacy_settings_seeds_nothing(self):
        await auth_db.init_db()
        assert await auth_db.list_users() == []

    @pytest.mark.asyncio
    async def test_legacy_settings_seed_one_user(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_username", "legacyadmin")
        monkeypatch.setattr(settings, "admin_password_hash", auth_db._hash("legacypass1"))
        await auth_db.init_db()

        user = await auth_db.get_user_by_username("legacyadmin")
        assert user is not None
        assert auth_db.verify_password("legacypass1", user["password_hash"])

    @pytest.mark.asyncio
    async def test_bootstrap_only_runs_on_empty_table(self, monkeypatch):
        await auth_db.init_db()
        await auth_db.create_user("someone", "someone@example.com", "somepassword1")

        monkeypatch.setattr(settings, "admin_username", "legacyadmin")
        monkeypatch.setattr(settings, "admin_password_hash", auth_db._hash("legacypass1"))
        await auth_db.init_db()  # table already has a row — must not seed the legacy user too

        assert await auth_db.get_user_by_username("legacyadmin") is None
        assert len(await auth_db.list_users()) == 1


# ── CRUD ──────────────────────────────────────────────────────────────────────

class TestUserCrud:
    @pytest.mark.asyncio
    async def test_create_and_fetch_user(self):
        await auth_db.init_db()
        created = await auth_db.create_user("alice", "alice@example.com", "password123")

        by_username = await auth_db.get_user_by_username("alice")
        by_email = await auth_db.get_user_by_email("alice@example.com")
        by_id = await auth_db.get_user_by_id(created["id"])

        assert by_username["id"] == by_email["id"] == by_id["id"]

    @pytest.mark.asyncio
    async def test_update_email(self):
        await auth_db.init_db()
        created = await auth_db.create_user("bob", "bob@example.com", "password123")
        await auth_db.update_email(created["id"], "bob.new@example.com")

        user = await auth_db.get_user_by_id(created["id"])
        assert user["email"] == "bob.new@example.com"

    @pytest.mark.asyncio
    async def test_update_password_changes_hash(self):
        await auth_db.init_db()
        created = await auth_db.create_user("carol", "carol@example.com", "password123")
        await auth_db.update_password(created["id"], "newpassword456")

        user = await auth_db.get_user_by_id(created["id"])
        assert auth_db.verify_password("newpassword456", user["password_hash"])
        assert not auth_db.verify_password("password123", user["password_hash"])

    @pytest.mark.asyncio
    async def test_delete_user(self):
        await auth_db.init_db()
        created = await auth_db.create_user("dave", "dave@example.com", "password123")
        await auth_db.delete_user(created["id"])

        assert await auth_db.get_user_by_id(created["id"]) is None


# ── Password reset tokens ─────────────────────────────────────────────────────

class TestResetTokens:
    @pytest.mark.asyncio
    async def test_valid_token_resolves_to_user_and_is_single_use(self):
        await auth_db.init_db()
        created = await auth_db.create_user("erin", "erin@example.com", "password123")
        token = await auth_db.create_reset_token(created["id"])

        assert await auth_db.consume_reset_token(token) == created["id"]
        # Second consumption of the same token must fail — single use.
        assert await auth_db.consume_reset_token(token) is None

    @pytest.mark.asyncio
    async def test_unknown_token_returns_none(self):
        await auth_db.init_db()
        assert await auth_db.consume_reset_token("not-a-real-token") is None

    @pytest.mark.asyncio
    async def test_expired_token_returns_none(self, monkeypatch):
        await auth_db.init_db()
        created = await auth_db.create_user("frank", "frank@example.com", "password123")
        monkeypatch.setattr(settings, "password_reset_token_expire_minutes", -1)  # already expired
        token = await auth_db.create_reset_token(created["id"])

        assert await auth_db.consume_reset_token(token) is None
