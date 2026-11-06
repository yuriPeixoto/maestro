"""Postgres: configuration and state (accounts, alert rules, channels and alert state).

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
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"
_ASYNC_DRIVER = "postgresql+asyncpg"

# Per-connection limits, so a stuck query or an abandoned transaction never holds
# the (shared) database: config and state queries take milliseconds.
_SESSION_SETTINGS = {
    "statement_timeout": "15s",
    "lock_timeout": "5s",
    "idle_in_transaction_session_timeout": "60s",
}

_engine: AsyncEngine | None = None
_sessions: async_sessionmaker[AsyncSession] | None = None
# Shown in pg_stat_activity, so each Maestro process can be told apart there.
_application_name = "maestro-api"


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


def set_application_name(name: str) -> None:
    """Name the connections of this process; call before the first query."""
    global _application_name
    _application_name = name


def get_engine() -> AsyncEngine:
    global _engine, _sessions
    if _engine is None:
        # Pool size 0 means one connection per use, closed right after (tests, scripts).
        pool_args = (
            {"poolclass": NullPool}
            if settings.database_pool_size == 0
            else {"pool_size": settings.database_pool_size, "pool_pre_ping": True}
        )
        server_settings = {"application_name": _application_name, **_SESSION_SETTINGS}
        _engine = create_async_engine(
            async_url(settings.database_url), connect_args={"server_settings": server_settings}, **pool_args,
        )
        _sessions = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


@asynccontextmanager
async def session(audit_action: str | None = None) -> AsyncIterator[AsyncSession]:
    """One unit of work: commits on success, rolls back on error.

    Inside a request, the caller is handed to the audit trigger for this transaction
    (app.audit); `audit_action` names the change in the log ("users.deactivate")
    instead of the table and operation.
    """
    from app import audit  # app.audit imports this module

    get_engine()
    assert _sessions is not None
    async with _sessions() as db, db.begin():
        values = audit.session_settings(audit_action)
        if values:
            names = list(values)
            calls = ", ".join(f"set_config(:name{i}, :value{i}, true)" for i in range(len(names)))
            params = {f"name{i}": name for i, name in enumerate(names)}
            params.update({f"value{i}": values[name] for i, name in enumerate(names)})
            await db.execute(text(f"SELECT {calls}"), params)
        yield db


class AdvisoryLock:
    """A Postgres advisory lock held on a connection of its own, so only one process
    at a time does the work it guards (today the alert evaluator).

    The lock lives as long as that connection: if Postgres restarts or the network
    drops it, `hold()` notices on its next call and tries to take the lock again,
    and another process may have it by then. The connection runs in autocommit, so
    holding it never leaves a transaction open.
    """

    def __init__(self, key: int) -> None:
        self._key = key
        self._conn: AsyncConnection | None = None

    async def hold(self) -> bool:
        """True while this process holds the lock; tries to take it when it does not."""
        if self._conn is not None:
            try:
                await self._conn.execute(text("SELECT 1"))
                return True
            except Exception:
                await self.release()
        conn = await get_engine().connect()
        try:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            taken = await conn.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": self._key})
        except Exception:
            await conn.close()
            raise
        if not taken:
            await conn.close()
            return False
        self._conn = conn
        return True

    async def release(self) -> None:
        """Closing the connection releases the lock, even when it is already broken."""
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            await conn.close()
        except Exception:
            await conn.invalidate()


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
