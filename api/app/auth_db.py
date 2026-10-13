from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import bcrypt

from app.config import settings

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    used       INTEGER NOT NULL DEFAULT 0
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


MIN_PASSWORD_LENGTH = 8


def validate_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")


async def init_db() -> None:
    """Create the schema and, on a fresh install, seed one account from the
    legacy MAESTRO_ADMIN_USERNAME/MAESTRO_ADMIN_PASSWORD_HASH settings so the
    upgrade doesn't lock out whoever was already using the single-admin login.
    """
    db_path = Path(settings.auth_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_SCHEMA)
        await _add_missing_columns(db)
        await db.commit()

        cursor = await db.execute("SELECT COUNT(*) FROM users")
        (count,) = await cursor.fetchone()

        if count == 0 and settings.admin_username and settings.admin_password_hash:
            now = _now()
            await db.execute(
                "INSERT INTO users (username, email, password_hash, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    settings.admin_username,
                    f"{settings.admin_username}@localhost",
                    settings.admin_password_hash,
                    now,
                    now,
                ),
            )
            await db.commit()
            logger.info(
                "auth_db: bootstrapped user '%s' from legacy admin settings — "
                "update its email via the Profile page",
                settings.admin_username,
            )


async def _add_missing_columns(db: aiosqlite.Connection) -> None:
    """Upgrade path for databases created before a column existed."""
    cursor = await db.execute("PRAGMA table_info(users)")
    columns = {row[1] for row in await cursor.fetchall()}
    if "must_change_password" not in columns:
        await db.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")


async def get_user_by_login(identifier: str) -> dict | None:
    """Resolve what the user typed on the login form: a username or an email."""
    return await get_user_by_username(identifier) or await get_user_by_email(identifier)


async def get_user_by_username(username: str) -> dict | None:
    async with aiosqlite.connect(settings.auth_db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_by_email(email: str) -> dict | None:
    async with aiosqlite.connect(settings.auth_db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_by_id(user_id: int) -> dict | None:
    async with aiosqlite.connect(settings.auth_db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_users() -> list[dict]:
    async with aiosqlite.connect(settings.auth_db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, username, email, created_at, updated_at FROM users ORDER BY username"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def create_user(username: str, email: str, password: str, must_change_password: bool = False) -> dict:
    """must_change_password marks a password chosen by someone other than the
    account owner: the account can do nothing but change it until it is replaced."""
    now = _now()
    password_hash = _hash(password)
    async with aiosqlite.connect(settings.auth_db_path) as db:
        cursor = await db.execute(
            "INSERT INTO users (username, email, password_hash, created_at, updated_at, must_change_password) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (username, email, password_hash, now, now, int(must_change_password)),
        )
        await db.commit()
        return {"id": cursor.lastrowid, "username": username, "email": email}


async def update_email(user_id: int, email: str) -> None:
    async with aiosqlite.connect(settings.auth_db_path) as db:
        await db.execute(
            "UPDATE users SET email = ?, updated_at = ? WHERE id = ?",
            (email, _now(), user_id),
        )
        await db.commit()


async def update_password(user_id: int, new_password: str) -> None:
    async with aiosqlite.connect(settings.auth_db_path) as db:
        await db.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0, updated_at = ? WHERE id = ?",
            (_hash(new_password), _now(), user_id),
        )
        await db.commit()


async def delete_user(user_id: int) -> None:
    async with aiosqlite.connect(settings.auth_db_path) as db:
        await db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await db.commit()


# ── Password reset tokens ───────────────────────────────────────────────────

async def create_reset_token(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=settings.password_reset_token_expire_minutes)
    ).isoformat()
    async with aiosqlite.connect(settings.auth_db_path) as db:
        await db.execute(
            "INSERT INTO password_reset_tokens (token, user_id, expires_at, used) VALUES (?, ?, ?, 0)",
            (token, user_id, expires_at),
        )
        await db.commit()
    return token


async def consume_reset_token(token: str) -> int | None:
    """Returns the user_id if the token is valid and unused, marking it used. None otherwise."""
    async with aiosqlite.connect(settings.auth_db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM password_reset_tokens WHERE token = ?", (token,)
        )
        row = await cursor.fetchone()
        if row is None or row["used"]:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            return None
        await db.execute("UPDATE password_reset_tokens SET used = 1 WHERE token = ?", (token,))
        await db.commit()
        return row["user_id"]
