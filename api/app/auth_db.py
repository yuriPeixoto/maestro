"""Accounts and password reset tokens, in Postgres (app.db).

Functions return plain dicts so the routers do not depend on the ORM. Timestamps
the API hands out (created_at, updated_at) are ISO 8601 strings, as before.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy import delete, func, select, update

from app import db, login_throttle
from app.config import settings
from app.models import PasswordResetToken, User
from app.release import VERSION

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 8

# Lockout: this many wrong passwords inside the window lock the account for one window.
# Same limits as the in-memory counter for identifiers without an account.
MAX_LOGIN_FAILURES = login_throttle.MAX_FAILURES
LOGIN_FAILURE_WINDOW = timedelta(seconds=login_throttle.WINDOW_SECONDS)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def validate_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")


def _as_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "password_hash": user.password_hash,
        "created_at": user.created_at.astimezone(timezone.utc).isoformat(),
        "updated_at": user.updated_at.astimezone(timezone.utc).isoformat(),
        "must_change_password": user.must_change_password,
        "last_seen_version": user.last_seen_version,
        "failed_login_count": user.failed_login_count,
        "locked_until": user.locked_until,
    }


async def bootstrap_legacy_admin() -> None:
    """On an empty users table, create one account from the legacy
    MAESTRO_ADMIN_USERNAME/MAESTRO_ADMIN_PASSWORD_HASH settings, so the upgrade from
    the old single-admin login does not lock out whoever was using it."""
    if not (settings.admin_username and settings.admin_password_hash):
        return
    async with db.session() as s:
        if await s.scalar(select(func.count()).select_from(User)):
            return
        s.add(User(
            username=settings.admin_username,
            email=f"{settings.admin_username}@localhost",
            password_hash=settings.admin_password_hash,
        ))
    logger.info(
        "auth_db: bootstrapped user '%s' from legacy admin settings — update its email via the Profile page",
        settings.admin_username,
    )


async def _get_one(*criteria) -> dict | None:
    async with db.session() as s:
        user = await s.scalar(select(User).where(*criteria))
        return _as_dict(user) if user else None


async def get_user_by_login(identifier: str) -> dict | None:
    """Resolve what the user typed on the login form: a username or an email."""
    return await get_user_by_username(identifier) or await get_user_by_email(identifier)


async def get_user_by_username(username: str) -> dict | None:
    return await _get_one(User.username == username)


async def get_user_by_email(email: str) -> dict | None:
    return await _get_one(User.email == email)


async def get_user_by_id(user_id: int) -> dict | None:
    return await _get_one(User.id == user_id)


async def list_users() -> list[dict]:
    async with db.session() as s:
        users = await s.scalars(select(User).order_by(User.username))
        return [
            {k: v for k, v in _as_dict(u).items() if k in ("id", "username", "email", "created_at", "updated_at")}
            for u in users
        ]


async def create_user(username: str, email: str, password: str, must_change_password: bool = False) -> dict:
    """must_change_password marks a password chosen by someone other than the
    account owner: the account can do nothing but change it until it is replaced."""
    async with db.session() as s:
        # A new account starts at the current version: there is nothing "new" to it yet.
        user = User(
            username=username,
            email=email,
            password_hash=_hash(password),
            must_change_password=must_change_password,
            last_seen_version=VERSION,
        )
        s.add(user)
        await s.flush()
        return {"id": user.id, "username": username, "email": email}


async def _update(user_id: int, **values) -> None:
    async with db.session() as s:
        await s.execute(update(User).where(User.id == user_id).values(**values))


async def mark_release_seen(user_id: int, version: str) -> None:
    await _update(user_id, last_seen_version=version)


async def update_email(user_id: int, email: str) -> None:
    await _update(user_id, email=email, updated_at=_now())


async def update_password(user_id: int, new_password: str) -> None:
    await _update(user_id, password_hash=_hash(new_password), must_change_password=False, updated_at=_now())


async def delete_user(user_id: int) -> None:
    async with db.session() as s:
        await s.execute(delete(User).where(User.id == user_id))


# ── Login lockout ─────────────────────────────────────────────────────────────

def seconds_locked(user: dict) -> int:
    """0 when the account may try to log in; otherwise how long it must wait."""
    locked_until = user["locked_until"]
    if locked_until is None:
        return 0
    remaining = (locked_until - _now()).total_seconds()
    return max(1, int(remaining)) if remaining > 0 else 0


async def record_login_failure(user_id: int) -> None:
    """Count a wrong password; the one that reaches the limit locks the account."""
    now = _now()
    async with db.session() as s:
        user = await s.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:
            return
        window_expired = user.last_failed_login_at is None or now - user.last_failed_login_at >= LOGIN_FAILURE_WINDOW
        user.failed_login_count = 1 if window_expired else user.failed_login_count + 1
        user.last_failed_login_at = now
        if user.failed_login_count >= MAX_LOGIN_FAILURES:
            user.locked_until = now + LOGIN_FAILURE_WINDOW
            user.failed_login_count = 0
            logger.warning("auth_db: account '%s' locked after %d failed logins", user.username, MAX_LOGIN_FAILURES)


async def clear_login_failures(user_id: int) -> None:
    await _update(user_id, failed_login_count=0, last_failed_login_at=None, locked_until=None)


# ── Password reset tokens ───────────────────────────────────────────────────

async def create_reset_token(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(minutes=settings.password_reset_token_expire_minutes)
    async with db.session() as s:
        s.add(PasswordResetToken(token=token, user_id=user_id, expires_at=expires_at))
    return token


async def consume_reset_token(token: str) -> int | None:
    """Returns the user_id if the token is valid and unused, marking it used. None otherwise."""
    async with db.session() as s:
        row = await s.scalar(select(PasswordResetToken).where(PasswordResetToken.token == token).with_for_update())
        if row is None or row.used or row.expires_at < _now():
            return None
        row.used = True
        return row.user_id
