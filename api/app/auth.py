from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

_oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── Models ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInfo(BaseModel):
    username: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _verify(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _make_token(username: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode({"sub": username, "exp": exp}, settings.jwt_secret, algorithm="HS256")


# ── Dependency ────────────────────────────────────────────────────────────────

async def get_current_user(token: str = Depends(_oauth2)) -> str:
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
    except JWTError:
        raise exc
    return username


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=Token)
async def login(body: LoginRequest) -> Token:
    if body.username != settings.admin_username or not _verify(body.password, settings.admin_password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return Token(access_token=_make_token(body.username))


@router.get("/me", response_model=UserInfo)
async def me(username: str = Depends(get_current_user)) -> UserInfo:
    return UserInfo(username=username)
