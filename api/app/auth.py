from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from pydantic import BaseModel, EmailStr, Field

from app import audit, auth_db, login_throttle
from app.config import settings
from app.permissions import Permission, allows, permissions_of
from app.release import VERSION, parse_version

router = APIRouter(prefix="/auth", tags=["auth"])

_oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")

_USER_AGENT_MAX = 300


# ── Models ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    must_change_password: bool


class UserInfo(BaseModel):
    id: int
    username: str
    email: str
    full_name: str | None = None
    role: str
    # The caller's permissions (app.permissions): the dashboard hides what is not here.
    permissions: list[str]
    must_change_password: bool = False
    last_seen_version: str | None = None


class ReleaseSeenRequest(BaseModel):
    version: str


class UpdateProfileRequest(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, max_length=120)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


def _validate_new_password(password: str) -> None:
    try:
        auth_db.validate_new_password(password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _make_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    # iat with sub-second precision: a token issued right after a temporary password
    # (same second) must not be mistaken for one issued before it.
    claims = {"sub": username, "iat": now.timestamp(), "exp": now + timedelta(minutes=settings.jwt_expire_minutes)}
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def _as_ip(value: str | None) -> str | None:
    """None for anything that is not an IP address (a Unix socket peer, a test client)."""
    if not value:
        return None
    try:
        return str(ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request: Request) -> str | None:
    """The caller's address. X-Forwarded-For counts only when the request came through
    a trusted proxy; its last entry is the one that proxy added."""
    peer = _as_ip(request.client.host if request.client else None)
    forwarded = request.headers.get("x-forwarded-for")
    if peer in settings.trusted_proxies and forwarded:
        return _as_ip(forwarded.split(",")[-1]) or peer
    return peer


def _user_agent(request: Request) -> str | None:
    agent = request.headers.get("user-agent")
    return agent[:_USER_AGENT_MAX] if agent else None


def _actor_for(user: dict | None, request: Request) -> audit.Actor:
    return audit.Actor(
        user_id=user["id"] if user else None,
        name=user["username"] if user else "anonymous",
        ip=client_ip(request),
        user_agent=_user_agent(request),
    )


# ── Dependency ────────────────────────────────────────────────────────────────

def _issued_before(payload: dict, moment: datetime | None) -> bool:
    if moment is None:
        return False
    issued_at = payload.get("iat")
    return not isinstance(issued_at, int | float) or issued_at < moment.timestamp()


async def get_current_user(request: Request, token: str = Depends(_oauth2)) -> dict:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        username: str | None = payload.get("sub")
        if not username:
            raise exc
    except jwt.InvalidTokenError:  # also covers an expired token
        raise exc

    user = await auth_db.get_user_by_username(username)
    if user is None or not user["active"] or _issued_before(payload, user["sessions_valid_after"]):
        raise exc
    audit.set_actor(_actor_for(user, request))
    await auth_db.touch_last_seen(user)
    return user


async def require_active_user(user: dict = Depends(get_current_user)) -> dict:
    """Everything except the account's own endpoints is closed while the
    password is still one somebody else chose."""
    if user["must_change_password"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password change required")
    return user


def require(permission: Permission) -> Callable[..., Coroutine[Any, Any, dict]]:
    """Route dependency: the caller's role must grant `permission` (app.permissions)."""
    async def check(user: dict = Depends(require_active_user)) -> dict:
        if not allows(user["role"], permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed for your role")
        return user

    check.required_permission = permission  # read by the test that checks every write route has one
    return check


def _user_info(user: dict) -> UserInfo:
    return UserInfo(
        id=user["id"],
        username=user["username"],
        email=user["email"],
        full_name=user.get("full_name"),
        role=user["role"],
        permissions=sorted(permissions_of(user["role"])),
        must_change_password=bool(user["must_change_password"]),
        last_seen_version=user.get("last_seen_version"),
    )


# ── Routes ────────────────────────────────────────────────────────────────────

def _too_many_attempts(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many failed attempts — try again later",
        headers={"Retry-After": str(retry_after)},
    )


_INVALID_CREDENTIALS = "Invalid credentials"


async def _login_failed(user: dict, request: Request, reason: str, locked: bool = False) -> HTTPException:
    details = {"reason": reason, "locked": True} if locked else {"reason": reason}
    await audit.record(
        "auth.login_failed", target_table="users", target_id=user["id"],
        details=details, actor=_actor_for(None, request),
    )
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS)


@router.post("/login", response_model=Token)
async def login(body: LoginRequest, request: Request) -> Token:
    user = await auth_db.get_user_by_login(body.username)

    # No such account: counted in memory, so a 429 does not reveal which accounts exist.
    if user is None:
        retry_after = login_throttle.seconds_until_allowed(body.username)
        if retry_after > 0:
            raise _too_many_attempts(retry_after)
        login_throttle.record_failure(body.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS)

    retry_after = auth_db.seconds_locked(user)
    if retry_after > 0:
        raise _too_many_attempts(retry_after)

    if not auth_db.verify_password(body.password, user["password_hash"]):
        locked = await auth_db.record_login_failure(user["id"])
        raise await _login_failed(user, request, "wrong_password", locked)

    # Same answer as a wrong password: a deactivated account looks like no account.
    if not user["active"]:
        raise await _login_failed(user, request, "deactivated")

    await auth_db.record_login(user["id"])
    await audit.record("auth.login", target_table="users", target_id=user["id"], actor=_actor_for(user, request))
    return Token(
        access_token=_make_token(user["username"]),
        username=user["username"],
        must_change_password=bool(user["must_change_password"]),
    )


@router.post("/logout")
async def logout(user: dict = Depends(get_current_user)) -> dict:
    # JWT is stateless — nothing to revoke server-side. The frontend discards its token.
    await audit.record("auth.logout", target_table="users", target_id=user["id"])
    return {"ok": True}


@router.get("/me", response_model=UserInfo)
async def me(user: dict = Depends(get_current_user)) -> UserInfo:
    return _user_info(user)


@router.post("/me/release-seen", status_code=status.HTTP_204_NO_CONTENT)
async def release_seen(body: ReleaseSeenRequest, user: dict = Depends(require_active_user)) -> None:
    """The release notes up to `version` were shown; only the running version or an older one is accepted."""
    try:
        seen = parse_version(body.version)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid version")
    if seen > parse_version(VERSION):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown version")
    await auth_db.mark_release_seen(user["id"], body.version)


@router.patch("/me", response_model=UserInfo)
async def update_me(body: UpdateProfileRequest, user: dict = Depends(require_active_user)) -> UserInfo:
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if "full_name" in changes:
        changes["full_name"] = changes["full_name"].strip() or None
    if "email" in changes:
        existing = await auth_db.get_user_by_email(changes["email"])
        if existing is not None and existing["id"] != user["id"]:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")
    if changes:
        await auth_db.update_own_profile(user["id"], **changes)
    return _user_info({**user, **changes})


@router.post("/change-password")
async def change_password(body: ChangePasswordRequest, user: dict = Depends(get_current_user)) -> dict:
    # 400, not 401: the session is valid, and the frontend logs out on any 401.
    if not auth_db.verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    _validate_new_password(body.new_password)
    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="New password must be different from the current one",
        )
    await auth_db.update_password(user["id"], body.new_password)
    return {"ok": True}
