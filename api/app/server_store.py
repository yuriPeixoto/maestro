"""Servers, groups and the names people give servers, in Postgres.

The hostname the agent reports (`server_id`) stays the identity everywhere shared: the
Telegram chat, the audit log, searches. A server may carry a shared `label`, set by an
admin and seen by everyone (notifications show it beside the hostname), and each account
may give it a personal nickname that only changes that account's screens.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import (
    AlertChannelRow,
    AlertRuleRow,
    AlertSilenceRow,
    ServerGroupRow,
    ServerNicknameRow,
    ServerRow,
)

LABEL_MAX_LENGTH = 60
NICKNAME_MAX_LENGTH = 60


@dataclass
class ServerGroup:
    group_id: int
    name: str
    description: str | None
    created_at: datetime


@dataclass
class ServerNames:
    server_id: str
    label: str | None
    group_id: int | None
    group_name: str | None
    nickname: str | None   # of the account that asked


class DuplicateName(Exception):
    """Another server (label), group (name) or of the account's servers (nickname) has it."""


class UnknownServer(Exception):
    pass


class UnknownGroup(Exception):
    pass


class GroupInUse(Exception):
    """Active rules, channels or silences still point at the group."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _group(row: ServerGroupRow) -> ServerGroup:
    return ServerGroup(group_id=row.group_id, name=row.name, description=row.description, created_at=row.created_at)


def clean_name(value: str | None) -> str | None:
    """Trimmed, inner runs of blanks collapsed; empty becomes None."""
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


# ── Servers ───────────────────────────────────────────────────────────────────

async def register_servers(server_ids: list[str]) -> int:
    """Add the servers Maestro has not seen before. Returns how many were added."""
    if not server_ids:
        return 0
    async with db.session() as s:
        known = set(await s.scalars(select(ServerRow.server_id).where(ServerRow.server_id.in_(server_ids))))
        missing = sorted(set(server_ids) - known)
        if not missing:
            return 0
        await s.execute(
            insert(ServerRow).values([{"server_id": server_id} for server_id in missing]).on_conflict_do_nothing()
        )
    return len(missing)


async def server_names(user_id: int, server_ids: list[str] | None = None) -> dict[str, ServerNames]:
    """Label, group and this account's nickname of each known server (or of these)."""
    nickname = (
        select(ServerNicknameRow.nickname)
        .where(ServerNicknameRow.server_id == ServerRow.server_id, ServerNicknameRow.user_id == user_id)
        .scalar_subquery()
    )
    query = (
        select(ServerRow.server_id, ServerRow.label, ServerRow.group_id, ServerGroupRow.name, nickname)
        .outerjoin(ServerGroupRow, ServerGroupRow.group_id == ServerRow.group_id)
    )
    if server_ids is not None:
        query = query.where(ServerRow.server_id.in_(server_ids))
    async with db.session() as s:
        rows = await s.execute(query)
        return {
            server_id: ServerNames(server_id, label, group_id, group_name, nick)
            for server_id, label, group_id, group_name, nick in rows
        }


async def labels(server_ids: list[str]) -> dict[str, str]:
    """{server_id: label} of the servers that have one."""
    if not server_ids:
        return {}
    async with db.session() as s:
        rows = await s.execute(
            select(ServerRow.server_id, ServerRow.label)
            .where(ServerRow.server_id.in_(server_ids), ServerRow.label.is_not(None))
        )
        return dict(rows.all())


async def label_of(server_id: str) -> str | None:
    return (await labels([server_id])).get(server_id)


_UNSET = object()


async def update_server(server_id: str, label=_UNSET, group_id=_UNSET) -> None:
    """Set the shared label and/or the group (None clears either)."""
    values: dict = {}
    if label is not _UNSET:
        values["label"] = clean_name(label)
    if group_id is not _UNSET:
        values["group_id"] = group_id
    try:
        async with db.session("servers.update") as s:
            if values.get("group_id") is not None:
                await _require_group(s, values["group_id"])
            query = select(ServerRow.server_id).where(ServerRow.server_id == server_id)
            if values:
                query = update(ServerRow).where(ServerRow.server_id == server_id).values(**values).returning(
                    ServerRow.server_id,
                )
            if await s.scalar(query) is None:
                raise UnknownServer()
    except IntegrityError as exc:
        if "servers_label_unique" in str(exc.orig):
            raise DuplicateName() from None
        raise


async def _require_group(s, group_id: int) -> None:
    found = await s.scalar(select(exists().where(ServerGroupRow.group_id == group_id, ServerGroupRow.deleted_at.is_(None))))
    if not found:
        raise UnknownGroup()


# ── Nicknames ─────────────────────────────────────────────────────────────────

async def set_nickname(user_id: int, server_id: str, nickname: str) -> str:
    """Give a server this account's own name for it. Raises DuplicateName when another of the
    account's servers has it (case aside), UnknownServer for a server Maestro does not know."""
    cleaned = clean_name(nickname)
    if cleaned is None:
        raise ValueError("A nickname cannot be empty")
    try:
        async with db.session() as s:
            if not await s.scalar(select(exists().where(ServerRow.server_id == server_id))):
                raise UnknownServer()
            await s.execute(
                insert(ServerNicknameRow)
                .values(user_id=user_id, server_id=server_id, nickname=cleaned)
                .on_conflict_do_update(
                    index_elements=["user_id", "server_id"],
                    set_={"nickname": cleaned},
                )
            )
    except IntegrityError as exc:
        if "server_nicknames_user_nickname_unique" in str(exc.orig):
            raise DuplicateName() from None
        raise
    return cleaned


async def clear_nickname(user_id: int, server_id: str) -> bool:
    async with db.session() as s:
        removed = await s.scalar(
            delete(ServerNicknameRow)
            .where(ServerNicknameRow.user_id == user_id, ServerNicknameRow.server_id == server_id)
            .returning(ServerNicknameRow.server_id)
        )
    return removed is not None


# ── Groups ────────────────────────────────────────────────────────────────────

_ACTIVE_GROUP = ServerGroupRow.deleted_at.is_(None)


async def list_groups() -> list[ServerGroup]:
    async with db.session() as s:
        rows = await s.scalars(select(ServerGroupRow).where(_ACTIVE_GROUP).order_by(func.lower(ServerGroupRow.name)))
        return [_group(r) for r in rows]


async def get_group(group_id: int) -> ServerGroup | None:
    async with db.session() as s:
        row = await s.scalar(select(ServerGroupRow).where(ServerGroupRow.group_id == group_id, _ACTIVE_GROUP))
        return _group(row) if row else None


async def create_group(name: str, description: str | None = None) -> ServerGroup:
    try:
        async with db.session() as s:
            row = await s.scalar(
                insert(ServerGroupRow)
                .values(name=clean_name(name), description=clean_name(description))
                .returning(ServerGroupRow)
            )
            return _group(row)
    except IntegrityError as exc:
        if "server_groups_name_unique" in str(exc.orig):
            raise DuplicateName() from None
        raise


async def update_group(group_id: int, name: str | None = None, description=_UNSET) -> ServerGroup:
    values: dict = {}
    if name is not None:
        values["name"] = clean_name(name)
    if description is not _UNSET:
        values["description"] = clean_name(description)
    if not values:
        group = await get_group(group_id)
        if group is None:
            raise UnknownGroup()
        return group
    try:
        async with db.session("server_groups.update") as s:
            row = await s.scalar(
                update(ServerGroupRow)
                .where(ServerGroupRow.group_id == group_id, _ACTIVE_GROUP)
                .values(**values)
                .returning(ServerGroupRow)
            )
            if row is None:
                raise UnknownGroup()
            return _group(row)
    except IntegrityError as exc:
        if "server_groups_name_unique" in str(exc.orig):
            raise DuplicateName() from None
        raise


async def delete_group(group_id: int) -> None:
    """Delete a group nothing else depends on; its servers are left without a group."""
    async with db.session("server_groups.delete") as s:
        if not await s.scalar(select(exists().where(ServerGroupRow.group_id == group_id, _ACTIVE_GROUP))):
            raise UnknownGroup()
        in_use = await s.scalar(select(or_(
            exists().where(AlertRuleRow.group_id == group_id, AlertRuleRow.deleted_at.is_(None)),
            exists().where(AlertChannelRow.group_id == group_id, AlertChannelRow.deleted_at.is_(None)),
            exists().where(AlertSilenceRow.group_id == group_id, func.upper(AlertSilenceRow.during) > func.now()),
        )))
        if in_use:
            raise GroupInUse()
        await s.execute(update(ServerRow).where(ServerRow.group_id == group_id).values(group_id=None))
        await s.execute(update(ServerGroupRow).where(ServerGroupRow.group_id == group_id).values(deleted_at=_now()))
