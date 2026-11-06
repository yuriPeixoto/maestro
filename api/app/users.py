"""Accounts, for admins: list, create, edit, deactivate and reactivate, and a temporary
password for someone who forgot theirs (there is no email reset)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app import auth_db, login_throttle
from app.auth import require
from app.permissions import ROLE_PERMISSIONS, Permission, Role

_manage_users = require(Permission.MANAGE_USERS)

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(_manage_users)])

_FULL_NAME_MAX = 120


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=_FULL_NAME_MAX)
    role: Role = Role.VIEWER
    # Omitted: the API generates one and returns it once, like a temporary password.
    password: str | None = None


class UpdateUserRequest(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, max_length=_FULL_NAME_MAX)
    role: Role | None = None


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    full_name: str | None
    role: Role
    active: bool
    must_change_password: bool
    created_at: str
    updated_at: str
    deactivated_at: str | None
    last_login_at: str | None
    last_seen_at: str | None


class CreatedUserOut(UserOut):
    temporary_password: str | None = None


class TemporaryPasswordOut(BaseModel):
    temporary_password: str


_LAST_ADMIN = "There must be at least one active admin"


async def _target(user_id: int) -> dict:
    target = await auth_db.get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return target


def _not_yourself(user_id: int, caller: dict, what: str) -> None:
    if user_id == caller["id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"You cannot {what} your own account")


async def _out(user_id: int) -> UserOut:
    return UserOut(**auth_db.public_view(await _target(user_id)))


class RoleOut(BaseModel):
    role: Role
    permissions: list[Permission]


class RolesOut(BaseModel):
    # Every permission, in the order the matrix lists them.
    permissions: list[Permission]
    roles: list[RoleOut]


@router.get("", response_model=list[UserOut])
async def list_users() -> list[UserOut]:
    return [UserOut(**row) for row in await auth_db.list_users()]


@router.get("/roles", response_model=RolesOut)
async def list_roles() -> RolesOut:
    """The permission matrix (app.permissions), so the screen shows the one the API enforces."""
    order = list(Permission)
    return RolesOut(
        permissions=order,
        roles=[
            RoleOut(role=role, permissions=[p for p in order if p in granted])
            for role, granted in ROLE_PERMISSIONS.items()
        ],
    )


@router.post("", response_model=CreatedUserOut, status_code=201)
async def create_user(body: CreateUserRequest) -> CreatedUserOut:
    if await auth_db.get_user_by_username(body.username) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    if await auth_db.get_user_by_email(body.email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")
    generated = body.password is None
    password = auth_db.generate_temporary_password() if generated else body.password
    try:
        auth_db.validate_new_password(password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    full_name = (body.full_name or "").strip() or None
    # The password was chosen by whoever created the account, not by its owner.
    created = await auth_db.create_user(
        body.username, body.email, password, must_change_password=True, full_name=full_name, role=body.role,
    )
    out = await _out(created["id"])
    return CreatedUserOut(**out.model_dump(), temporary_password=password if generated else None)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: int, body: UpdateUserRequest, caller: dict = Depends(_manage_users)) -> UserOut:
    target = await _target(user_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    role = changes.pop("role", None)
    if role is not None and role != target["role"]:
        _not_yourself(user_id, caller, "change the role of")
    else:
        role = None
    if "full_name" in changes:
        changes["full_name"] = changes["full_name"].strip() or None
    if "email" in changes and changes["email"] != target["email"]:
        existing = await auth_db.get_user_by_email(changes["email"])
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already in use")
    try:
        await auth_db.update_user(user_id, role=role, **changes)
    except auth_db.LastAdminError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_LAST_ADMIN)
    return await _out(user_id)


@router.post("/{user_id}/deactivate", response_model=UserOut)
async def deactivate_user(user_id: int, caller: dict = Depends(_manage_users)) -> UserOut:
    _not_yourself(user_id, caller, "deactivate")
    target = await _target(user_id)
    if target["active"]:
        try:
            await auth_db.deactivate_user(user_id)
        except auth_db.LastAdminError:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_LAST_ADMIN)
    return await _out(user_id)


@router.post("/{user_id}/reactivate", response_model=UserOut)
async def reactivate_user(user_id: int) -> UserOut:
    target = await _target(user_id)
    if not target["active"]:
        await auth_db.reactivate_user(user_id)
    return await _out(user_id)


@router.post("/{user_id}/temporary-password", response_model=TemporaryPasswordOut)
async def temporary_password(user_id: int, caller: dict = Depends(_manage_users)) -> TemporaryPasswordOut:
    """For someone who forgot their password: shown once, to be passed on in person.
    Your own password changes from the Profile screen."""
    _not_yourself(user_id, caller, "set a temporary password for")
    target = await _target(user_id)
    if not target["active"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Reactivate the account first")
    password = await auth_db.set_temporary_password(user_id)
    login_throttle.reset(target["username"])
    login_throttle.reset(target["email"])
    return TemporaryPasswordOut(temporary_password=password)
