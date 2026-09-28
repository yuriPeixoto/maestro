from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr

from app import auth_db
from app.config import settings
from app.password_reset_mail import send_reset_email

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
    id: int
    username: str
    email: str


class UpdateEmailRequest(BaseModel):
    email: EmailStr


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


def _validate_new_password(password: str) -> None:
    try:
        auth_db.validate_new_password(password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


def _make_token(username: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode({"sub": username, "exp": exp}, settings.jwt_secret, algorithm="HS256")


# ── Dependency ────────────────────────────────────────────────────────────────

async def get_current_user(token: str = Depends(_oauth2)) -> dict:
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

    user = await auth_db.get_user_by_username(username)
    if user is None:
        raise exc
    return user


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=Token)
async def login(body: LoginRequest) -> Token:
    user = await auth_db.get_user_by_username(body.username)
    if user is None or not auth_db.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return Token(access_token=_make_token(user["username"]))


@router.post("/logout")
async def logout() -> dict:
    # JWT is stateless — nothing to revoke server-side. The frontend discards its token.
    return {"ok": True}


@router.get("/me", response_model=UserInfo)
async def me(user: dict = Depends(get_current_user)) -> UserInfo:
    return UserInfo(id=user["id"], username=user["username"], email=user["email"])


@router.patch("/me", response_model=UserInfo)
async def update_me(body: UpdateEmailRequest, user: dict = Depends(get_current_user)) -> UserInfo:
    existing = await auth_db.get_user_by_email(body.email)
    if existing is not None and existing["id"] != user["id"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")
    await auth_db.update_email(user["id"], body.email)
    return UserInfo(id=user["id"], username=user["username"], email=body.email)


@router.post("/change-password")
async def change_password(body: ChangePasswordRequest, user: dict = Depends(get_current_user)) -> dict:
    if not auth_db.verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    _validate_new_password(body.new_password)
    await auth_db.update_password(user["id"], body.new_password)
    return {"ok": True}


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest) -> dict:
    user = await auth_db.get_user_by_email(body.email)
    # Always return 200 regardless of whether the email exists — avoids leaking which
    # addresses have an account.
    if user is not None:
        token = await auth_db.create_reset_token(user["id"])
        await send_reset_email(user["email"], token)
    return {"ok": True}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest) -> dict:
    user_id = await auth_db.consume_reset_token(body.token)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
    _validate_new_password(body.new_password)
    await auth_db.update_password(user_id, body.new_password)
    return {"ok": True}
