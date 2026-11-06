"""Accounts, in Postgres (app.db).

Functions return plain dicts so the routers do not depend on the ORM. Timestamps
the API hands out (created_at, updated_at, last_login_at...) are ISO 8601 strings.
Accounts are never deleted: they are deactivated, so the audit log keeps pointing at them.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy import func, select, update

from app import db, login_throttle
from app.config import settings
from app.models import User
from app.permissions import Role
from app.release import VERSION

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 8

# Temporary passwords: long enough to be safe for the hours until the owner replaces it,
# from an alphabet without look-alikes (0/O, 1/l/I), so it can be read out loud.
TEMPORARY_PASSWORD_LENGTH = 14
TEMPORARY_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"

# last_seen_at is written at most this often per account, not on every request.
LAST_SEEN_RESOLUTION = timedelta(minutes=5)

# Lockout: this many wrong passwords inside the window lock the account for one window.
# Same limits as the in-memory counter for identifiers without an account.
MAX_LOGIN_FAILURES = login_throttle.MAX_FAILURES
LOGIN_FAILURE_WINDOW = timedelta(seconds=login_throttle.WINDOW_SECONDS)


class LastAdminError(Exception):
    """The change would leave no active admin."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(timezone.utc).isoformat()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def validate_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")


def generate_temporary_password() -> str:
    return "".join(secrets.choice(TEMPORARY_PASSWORD_ALPHABET) for _ in range(TEMPORARY_PASSWORD_LENGTH))


def _as_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "active": user.deactivated_at is None,
        "password_hash": user.password_hash,
        "created_at": _iso(user.created_at),
        "updated_at": _iso(user.updated_at),
        "deactivated_at": _iso(user.deactivated_at),
        "last_login_at": _iso(user.last_login_at),
        "last_seen_at": user.last_seen_at,
        "sessions_valid_after": user.sessions_valid_after,
        "must_change_password": user.must_change_password,
        "last_seen_version": user.last_seen_version,
        "failed_login_count": user.failed_login_count,
        "locked_until": user.locked_until,
    }


_PUBLIC_FIELDS = (
    "id", "username", "email", "full_name", "role", "active", "must_change_password",
    "created_at", "updated_at", "deactivated_at", "last_login_at",
)


def public_view(user: dict) -> dict:
    """What the Users screen may see of an account: no hash, no lockout counters."""
    view = {key: user[key] for key in _PUBLIC_FIELDS}
    view["last_seen_at"] = _iso(user["last_seen_at"])
    return view


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
            role=Role.ADMIN,
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
    """Active accounts first, then by username."""
    async with db.session() as s:
        users = await s.scalars(select(User).order_by(User.deactivated_at.is_not(None), User.username))
        return [public_view(_as_dict(u)) for u in users]


async def create_user(
    username: str,
    email: str,
    password: str,
    must_change_password: bool = False,
    *,
    full_name: str | None = None,
    role: Role = Role.VIEWER,
) -> dict:
    """must_change_password marks a password chosen by someone other than the
    account owner: the account can do nothing but change it until it is replaced."""
    async with db.session() as s:
        # A new account starts at the current version: there is nothing "new" to it yet.
        user = User(
            username=username,
            email=email,
            full_name=full_name,
            role=role,
            password_hash=_hash(password),
            must_change_password=must_change_password,
            last_seen_version=VERSION,
        )
        s.add(user)
        await s.flush()
        return {"id": user.id, "username": username, "email": email}


async def _update(user_id: int, audit_action: str | None = None, **values) -> None:
    async with db.session(audit_action) as s:
        await s.execute(update(User).where(User.id == user_id).values(**values))


async def mark_release_seen(user_id: int, version: str) -> None:
    await _update(user_id, last_seen_version=version)


async def update_own_profile(user_id: int, **values) -> None:
    """email and/or full_name, from the Profile screen."""
    await _update(user_id, "users.update_profile", updated_at=_now(), **values)


async def update_password(user_id: int, new_password: str) -> None:
    await _update(
        user_id, "users.change_password",
        password_hash=_hash(new_password), must_change_password=False, updated_at=_now(),
    )


# ── Admin changes ─────────────────────────────────────────────────────────────

async def _lock_active_admins(s) -> set[int]:
    """Locks every active admin row, so two admins demoting each other at the same
    moment cannot both pass the "someone is left" check."""
    rows = await s.scalars(
        select(User.id).where(User.role == Role.ADMIN, User.deactivated_at.is_(None)).with_for_update()
    )
    return set(rows)


async def update_user(user_id: int, *, role: Role | None = None, **values) -> None:
    """Name, email and role. Raises LastAdminError when the role change would leave no active admin."""
    async with db.session("users.update") as s:
        if role is not None and role != Role.ADMIN:
            admins = await _lock_active_admins(s)
            if admins == {user_id}:
                raise LastAdminError
        if role is not None:
            values["role"] = role
        if not values:
            return
        await s.execute(update(User).where(User.id == user_id).values(updated_at=_now(), **values))


async def deactivate_user(user_id: int) -> None:
    """Login and open sessions are refused from now on. Raises LastAdminError for the last active admin."""
    now = _now()
    async with db.session("users.deactivate") as s:
        admins = await _lock_active_admins(s)
        if admins == {user_id}:
            raise LastAdminError
        await s.execute(
            update(User).where(User.id == user_id, User.deactivated_at.is_(None))
            .values(deactivated_at=now, sessions_valid_after=now, updated_at=now)
        )


async def reactivate_user(user_id: int) -> None:
    await _update(user_id, "users.reactivate", deactivated_at=None, updated_at=_now())


async def set_temporary_password(user_id: int) -> str:
    """A new random password the owner must replace on the next login. Clears the
    lockout and ends the account's open sessions. Returns it in clear, once."""
    password = generate_temporary_password()
    now = _now()
    await _update(
        user_id, "users.temporary_password",
        password_hash=_hash(password), must_change_password=True, sessions_valid_after=now,
        failed_login_count=0, last_failed_login_at=None, locked_until=None, updated_at=now,
    )
    return password


# ── Access ────────────────────────────────────────────────────────────────────

async def record_login(user_id: int) -> None:
    now = _now()
    await _update(
        user_id, last_login_at=now, last_seen_at=now,
        failed_login_count=0, last_failed_login_at=None, locked_until=None,
    )


async def touch_last_seen(user: dict) -> None:
    """Called on every authenticated request; writes only when the stored value is old."""
    now = _now()
    last_seen = user["last_seen_at"]
    if last_seen is not None and now - last_seen < LAST_SEEN_RESOLUTION:
        return
    await _update(user["id"], last_seen_at=now)


# ── Login lockout ─────────────────────────────────────────────────────────────

def seconds_locked(user: dict) -> int:
    """0 when the account may try to log in; otherwise how long it must wait."""
    locked_until = user["locked_until"]
    if locked_until is None:
        return 0
    remaining = (locked_until - _now()).total_seconds()
    return max(1, int(remaining)) if remaining > 0 else 0


async def record_login_failure(user_id: int) -> bool:
    """Count a wrong password; the one that reaches the limit locks the account (returns True)."""
    now = _now()
    async with db.session() as s:
        user = await s.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:
            return False
        window_expired = user.last_failed_login_at is None or now - user.last_failed_login_at >= LOGIN_FAILURE_WINDOW
        user.failed_login_count = 1 if window_expired else user.failed_login_count + 1
        user.last_failed_login_at = now
        if user.failed_login_count >= MAX_LOGIN_FAILURES:
            user.locked_until = now + LOGIN_FAILURE_WINDOW
            user.failed_login_count = 0
            logger.warning("auth_db: account '%s' locked after %d failed logins", user.username, MAX_LOGIN_FAILURES)
            return True
        return False


async def clear_login_failures(user_id: int) -> None:
    await _update(user_id, failed_login_count=0, last_failed_login_at=None, locked_until=None)
