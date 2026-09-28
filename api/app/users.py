from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from app import auth_db
from app.auth import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


class CreateUserRequest(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    created_at: str


@router.get("", response_model=list[UserOut])
async def list_users(_user: dict = Depends(get_current_user)) -> list[UserOut]:
    rows = await auth_db.list_users()
    return [UserOut(**row) for row in rows]


@router.post("", response_model=UserOut, status_code=201)
async def create_user(body: CreateUserRequest, _user: dict = Depends(get_current_user)) -> UserOut:
    if await auth_db.get_user_by_username(body.username) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    if await auth_db.get_user_by_email(body.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")
    try:
        auth_db.validate_new_password(body.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    created = await auth_db.create_user(body.username, body.email, body.password)
    full = await auth_db.get_user_by_id(created["id"])
    return UserOut(**full)


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: int, user: dict = Depends(get_current_user)) -> None:
    if user_id == user["id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account")
    target = await auth_db.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await auth_db.delete_user(user_id)
