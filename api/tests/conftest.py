"""Shared fixtures. Tests that touch Postgres ask for the `postgres` fixture.

Point MAESTRO_TEST_DATABASE_URL at a disposable database whose name contains
"test" (its tables are emptied before every test). Without it those tests are
skipped, unless MAESTRO_REQUIRE_TEST_DATABASE=1 (CI), which turns the skip into
a failure so they can never pass by not running.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app import db
from app.config import settings

_ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
_TABLES = (
    "alert_state", "alert_channels", "alert_rules", "alert_defaults_applied",
    "audit_log", "users",
)


def _test_database_url() -> str:
    url = os.environ.get("MAESTRO_TEST_DATABASE_URL", "")
    if not url:
        reason = "MAESTRO_TEST_DATABASE_URL is not set"
        if os.environ.get("MAESTRO_REQUIRE_TEST_DATABASE") == "1":
            pytest.fail(f"{reason}, and MAESTRO_REQUIRE_TEST_DATABASE=1")
        pytest.skip(reason)
    if "test" not in (make_url(url).database or ""):
        pytest.fail("MAESTRO_TEST_DATABASE_URL must name a database with 'test' in it: its tables get emptied")
    return url


@pytest.fixture(scope="session")
def postgres_url() -> str:
    """Brings the test database to the newest migration, once per run."""
    url = _test_database_url()
    config = Config(str(_ALEMBIC_INI))
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
    return url


async def _truncate(url: str) -> None:
    engine = create_async_engine(db.async_url(url), poolclass=NullPool)
    async with engine.begin() as conn:
        # audit_log refuses TRUNCATE, and the audited tables log one: neither applies to emptying the test database.
        await conn.execute(text("SET LOCAL session_replication_role = replica"))
        await conn.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest.fixture
def postgres(postgres_url, monkeypatch) -> str:
    """Empty tables and an app.db engine pointed at the test database."""
    asyncio.run(_truncate(postgres_url))
    monkeypatch.setattr(settings, "database_url", postgres_url)
    monkeypatch.setattr(settings, "database_pool_size", 0)
    asyncio.run(db.dispose_engine())
    yield postgres_url
    asyncio.run(db.dispose_engine())


def act_as(app, role: str = "admin", user_id: int = 1, username: str = "tester") -> dict:
    """Skips the token: routes behind require_active_user (and app.auth.require) see this account."""
    from app.auth import require_active_user

    user = {
        "id": user_id, "username": username, "email": f"{username}@example.com", "full_name": None,
        "role": role, "active": True, "must_change_password": False, "last_seen_version": None,
    }
    app.dependency_overrides[require_active_user] = lambda: user
    return user
