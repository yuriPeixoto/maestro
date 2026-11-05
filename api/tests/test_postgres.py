"""The Postgres store itself: URL checks, the schema check at startup, and the
one-time import of the accounts kept in SQLite by 0.1.0."""
from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import text

from app import auth_db, db
from app.import_sqlite import import_users, read_sqlite_users

# The SQLite schema as 0.1.0 left it.
_SQLITE_SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 0, last_seen_version TEXT
);
"""


class TestDatabaseUrl:
    def test_a_missing_url_stops_startup(self):
        with pytest.raises(RuntimeError, match="MAESTRO_DATABASE_URL is not set"):
            db.check_database_url("")

    def test_only_postgres_is_accepted(self):
        with pytest.raises(RuntimeError, match="postgresql://"):
            db.check_database_url("sqlite:///data/maestro_auth.db")

    def test_the_plain_form_goes_through_asyncpg(self):
        url = db.async_url("postgresql://maestro_app:s3cret@db.local:5432/maestro")

        assert url == "postgresql+asyncpg://maestro_app:s3cret@db.local:5432/maestro"


@pytest.mark.usefixtures("postgres")
class TestSchemaCheck:
    @pytest.mark.asyncio
    async def test_a_current_schema_passes(self):
        await db.check_schema_is_current()

    @pytest.mark.asyncio
    async def test_a_database_behind_the_code_stops_startup(self):
        async with db.session() as s:
            await s.execute(text("UPDATE alembic_version SET version_num = 'older'"))
        try:
            with pytest.raises(RuntimeError, match="the code expects"):
                await db.check_schema_is_current()
        finally:
            async with db.session() as s:
                await s.execute(text("UPDATE alembic_version SET version_num = :head"), {"head": db.schema_head()})


def _sqlite_with(path, rows: list[tuple]) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(_SQLITE_SCHEMA)
        conn.executemany(
            "INSERT INTO users (username, email, password_hash, created_at, updated_at, must_change_password,"
            " last_seen_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    conn.close()


@pytest.mark.usefixtures("postgres")
class TestImportSqlite:
    @pytest.mark.asyncio
    async def test_copies_accounts_and_keeps_their_passwords(self, tmp_path):
        path = tmp_path / "maestro_auth.db"
        _sqlite_with(path, [
            ("ana", "ana@example.com", auth_db._hash("ana-password"), "2026-10-13T12:00:00+00:00",
             "2026-10-20T08:30:00+00:00", 0, "0.1.0"),
            ("beto", "beto@example.com", auth_db._hash("beto-password"), "2026-10-13T12:00:00", "2026-10-13T12:00:00",
             1, None),
        ])

        report = await import_users(read_sqlite_users(path))

        assert [outcome for _name, outcome in report] == ["copied", "copied"]
        ana = await auth_db.get_user_by_username("ana")
        beto = await auth_db.get_user_by_username("beto")
        assert auth_db.verify_password("ana-password", ana["password_hash"])
        assert (ana["must_change_password"], ana["last_seen_version"]) == (False, "0.1.0")
        assert (beto["must_change_password"], beto["last_seen_version"]) == (True, None)
        assert ana["created_at"] == "2026-10-13T12:00:00+00:00"

    @pytest.mark.asyncio
    async def test_running_again_neither_duplicates_nor_overwrites(self, tmp_path):
        path = tmp_path / "maestro_auth.db"
        _sqlite_with(path, [
            ("caio", "caio@example.com", auth_db._hash("old-password"), "2026-10-13T12:00:00+00:00",
             "2026-10-13T12:00:00+00:00", 1, None),
        ])
        await import_users(read_sqlite_users(path))
        caio = await auth_db.get_user_by_username("caio")
        await auth_db.update_password(caio["id"], "changed-in-postgres")

        report = await import_users(read_sqlite_users(path))

        assert [outcome.split(" ")[0] for _name, outcome in report] == ["already"]
        assert len(await auth_db.list_users()) == 1
        caio = await auth_db.get_user_by_username("caio")
        assert auth_db.verify_password("changed-in-postgres", caio["password_hash"])

    @pytest.mark.asyncio
    async def test_an_email_already_taken_is_skipped(self, tmp_path):
        await auth_db.create_user("dora", "shared@example.com", "password123")
        path = tmp_path / "maestro_auth.db"
        _sqlite_with(path, [
            ("dani", "shared@example.com", auth_db._hash("x-password"), "2026-10-13T12:00:00+00:00",
             "2026-10-13T12:00:00+00:00", 0, None),
        ])

        report = await import_users(read_sqlite_users(path))

        assert report[0][1].startswith("already")
        assert await auth_db.get_user_by_username("dani") is None

    def test_a_missing_file_is_an_error_not_an_empty_import(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_sqlite_users(tmp_path / "nope.db")
