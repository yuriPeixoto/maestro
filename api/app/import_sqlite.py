"""Copy the accounts from the SQLite store of 0.1.0 into Postgres.

    python -m app.import_sqlite data/maestro_auth.db

Copies username, email, password hash, the pending password change, the last
release seen and the dates. Safe to run again: an account whose username or email
is already in Postgres is skipped, never overwritten, so a password changed after
the first import is kept. The SQLite file is only read. Reset tokens are not copied.
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import or_, select

from app import db
from app.config import settings
from app.models import User

_COPIED = "copied"
_SKIPPED = "already in Postgres — skipped"


def _timestamp(value: str | None) -> datetime:
    """SQLite kept ISO 8601 text; anything unreadable becomes now (UTC)."""
    try:
        parsed = datetime.fromisoformat(value or "")
    except ValueError:
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def read_sqlite_users(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"No SQLite file at {path}")
    # mode=ro: the source stays untouched, it is the way back.
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    return [
        {
            "username": row["username"],
            "email": row["email"],
            "password_hash": row["password_hash"],
            "created_at": _timestamp(row["created_at"]),
            "updated_at": _timestamp(row["updated_at"]),
            "must_change_password": bool(row["must_change_password"]) if "must_change_password" in columns else False,
            "last_seen_version": row["last_seen_version"] if "last_seen_version" in columns else None,
        }
        for row in rows
    ]


async def import_users(users: list[dict]) -> list[tuple[str, str]]:
    """Returns (username, outcome) per account."""
    report: list[tuple[str, str]] = []
    for user in users:
        async with db.session() as s:
            existing = await s.scalar(
                select(User.id).where(or_(User.username == user["username"], User.email == user["email"]))
            )
            if existing is not None:
                report.append((user["username"], _SKIPPED))
                continue
            s.add(User(**user))
        report.append((user["username"], _COPIED))
    return report


async def _run(path: Path) -> list[tuple[str, str]]:
    try:
        return await import_users(read_sqlite_users(path))
    finally:
        await db.dispose_engine()


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    db.check_database_url(settings.database_url)

    report = asyncio.run(_run(Path(sys.argv[1])))
    for username, outcome in report:
        print(f"{username}: {outcome}")
    copied = sum(outcome == _COPIED for _name, outcome in report)
    print(f"{copied} copied, {len(report) - copied} skipped, {len(report)} in the SQLite file")


if __name__ == "__main__":
    main()
