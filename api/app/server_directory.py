"""Server groups, the shared label of a server, and each account's own nickname for it.

Groups and labels are configuration (admins, audited). A nickname is a preference of
the account that sets it: every role may manage its own, and only its screens change.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app import server_store
from app.auth import require, require_active_user
from app.permissions import Permission
from app.server_store import LABEL_MAX_LENGTH, NICKNAME_MAX_LENGTH, ServerGroup

router = APIRouter(tags=["servers"])

_MANAGE_SERVERS = [Depends(require(Permission.MANAGE_SERVERS))]
_NAME_MAX_LENGTH = 60
_DESCRIPTION_MAX_LENGTH = 300


class ServerChangesIn(BaseModel):
    """Only the fields sent change; null clears the label or takes the server out of its group."""
    label: str | None = Field(default=None, max_length=LABEL_MAX_LENGTH)
    group_id: int | None = None


class NicknameIn(BaseModel):
    nickname: str = Field(min_length=1, max_length=NICKNAME_MAX_LENGTH)


class NicknameOut(BaseModel):
    server_id: str
    nickname: str


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=_NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX_LENGTH)


class GroupChangesIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX_LENGTH)


class GroupOut(BaseModel):
    group_id: int
    name: str
    description: str | None


def _group_out(group: ServerGroup) -> GroupOut:
    return GroupOut(group_id=group.group_id, name=group.name, description=group.description)


# ── A server's names ──────────────────────────────────────────────────────────

@router.patch("/servers/{server_id}", status_code=204, dependencies=_MANAGE_SERVERS)
async def update_server(server_id: str, body: ServerChangesIn) -> Response:
    changes = body.model_dump(exclude_unset=True)
    try:
        await server_store.update_server(server_id, **changes)
    except server_store.UnknownServer:
        raise HTTPException(status_code=404, detail="Server not found") from None
    except server_store.UnknownGroup:
        raise HTTPException(status_code=404, detail="Group not found") from None
    except server_store.DuplicateName:
        raise HTTPException(status_code=409, detail="Another server already has this label") from None
    return Response(status_code=204)


# Any role: see app.permissions and the named exception in tests/test_roles.py.
@router.put("/servers/{server_id}/nickname", response_model=NicknameOut)
async def set_nickname(server_id: str, body: NicknameIn, user: dict = Depends(require_active_user)) -> NicknameOut:
    try:
        nickname = await server_store.set_nickname(user["id"], server_id, body.nickname)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except server_store.UnknownServer:
        raise HTTPException(status_code=404, detail="Server not found") from None
    except server_store.DuplicateName:
        raise HTTPException(status_code=409, detail="You already use this name for another server") from None
    return NicknameOut(server_id=server_id, nickname=nickname)


@router.delete("/servers/{server_id}/nickname", status_code=204)
async def clear_nickname(server_id: str, user: dict = Depends(require_active_user)) -> Response:
    await server_store.clear_nickname(user["id"], server_id)
    return Response(status_code=204)


# ── Groups ────────────────────────────────────────────────────────────────────

@router.get("/server-groups", response_model=list[GroupOut])
async def list_groups() -> list[GroupOut]:
    return [_group_out(g) for g in await server_store.list_groups()]


@router.post("/server-groups", response_model=GroupOut, status_code=201, dependencies=_MANAGE_SERVERS)
async def create_group(body: GroupIn) -> GroupOut:
    try:
        return _group_out(await server_store.create_group(body.name, body.description))
    except server_store.DuplicateName:
        raise HTTPException(status_code=409, detail="A group with this name exists") from None


@router.patch("/server-groups/{group_id}", response_model=GroupOut, dependencies=_MANAGE_SERVERS)
async def update_group(group_id: int, body: GroupChangesIn) -> GroupOut:
    changes = body.model_dump(exclude_unset=True)
    try:
        return _group_out(await server_store.update_group(group_id, **changes))
    except server_store.UnknownGroup:
        raise HTTPException(status_code=404, detail="Group not found") from None
    except server_store.DuplicateName:
        raise HTTPException(status_code=409, detail="A group with this name exists") from None


@router.delete("/server-groups/{group_id}", status_code=204, dependencies=_MANAGE_SERVERS)
async def delete_group(group_id: int) -> Response:
    try:
        await server_store.delete_group(group_id)
    except server_store.UnknownGroup:
        raise HTTPException(status_code=404, detail="Group not found") from None
    except server_store.GroupInUse:
        raise HTTPException(
            status_code=409, detail="Rules, channels or silences still use this group; move or delete them first",
        ) from None
    return Response(status_code=204)
