"""Postgres: configuration and state (accounts now; rules, channels and alert state next).

History stays in ClickHouse (ADR-011). The schema belongs to Alembic (`api/alembic/`):
the API never creates or alters tables, and refuses to start when the database is
behind the code (see check_schema_is_current).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"
_ASYNC_DRIVER = "postgresql+asyncpg"

_engine: AsyncEngine | None = None
_sessions: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
    pass


def async_url(url: str) -> str:
    """Accept the plain postgresql:// form too; the API always talks through asyncpg."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        raise RuntimeError("MAESTRO_DATABASE_URL must be a postgresql:// URL")
    return parsed.set(drivername=_ASYNC_DRIVER).render_as_string(hide_password=False)


def check_database_url(url: str) -> None:
    if not url:
        raise RuntimeError(
            "MAESTRO_DATABASE_URL is not set, e.g. postgresql://maestro_app:<password>@localhost:5432/maestro"
        )
    async_url(url)


def get_engine() -> AsyncEngine:
    global _engine, _sessions
    if _engine is None:
        # Pool size 0 means one connection per use, closed right after (tests, scripts).
        pool_args = (
            {"poolclass": NullPool}
            if settings.database_pool_size == 0
            else {"pool_size": settings.database_pool_size, "pool_pre_ping": True}
        )
        _engine = create_async_engine(async_url(settings.database_url), **pool_args)
        _sessions = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    """One unit of work: commits on success, rolls back on error."""
    get_engine()
    assert _sessions is not None
    async with _sessions() as db, db.begin():
        yield db


async def dispose_engine() -> None:
    global _engine, _sessions
    if _engine is not None:
        await _engine.dispose()
    _engine, _sessions = None, None


def schema_head() -> str:
    script = ScriptDirectory.from_config(Config(str(_ALEMBIC_INI)))
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("Alembic has no migrations")
    return head


async def check_schema_is_current() -> None:
    """Fail startup on a database that is missing migrations, instead of on the first query."""
    head = schema_head()
    async with get_engine().connect() as conn:
        has_version_table = await conn.scalar(text("SELECT to_regclass('alembic_version') IS NOT NULL"))
        current = await conn.scalar(text("SELECT version_num FROM alembic_version")) if has_version_table else None
    if current != head:
        raise RuntimeError(
            f"Database schema is at {current or 'nothing'}, the code expects {head}. "
            "Apply the migrations first (docs/deployment.md, \"Postgres\")."
        )
