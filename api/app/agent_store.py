"""What the agents tell about themselves on their `events` subject, kept in Postgres (ADR-015):
the agent registry, the OS package snapshot and the database connection lists.

Every write is keyed by the server the message was published as and keeps only the newest by the
time the agent sent it, so a late or repeated delivery changes nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app import db
from app.models import AgentRow, DBSnapshotRow, ServerPackagesRow


@dataclass(frozen=True)
class Agent:
    server_id: str
    hostname: str
    os: str
    tags: list[str]
    agent_version: str
    registered_at: datetime
    deregistered_at: datetime | None


def _agent(row: AgentRow) -> Agent:
    return Agent(
        server_id=row.server_id, hostname=row.hostname, os=row.os, tags=list(row.tags),
        agent_version=row.agent_version, registered_at=row.registered_at, deregistered_at=row.deregistered_at,
    )


async def record_registration(
    server_id: str, hostname: str, os: str, tags: list[str], agent_version: str, sent_at: datetime,
) -> None:
    """The agent started (or a user registered it over HTTP). Clears an earlier goodbye."""
    values = {
        "server_id": server_id, "hostname": hostname, "os": os, "tags": tags, "agent_version": agent_version,
        "registered_at": sent_at, "deregistered_at": None, "event_at": sent_at,
    }
    statement = insert(AgentRow).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=[AgentRow.server_id],
        set_={key: statement.excluded[key] for key in values if key != "server_id"},
        where=AgentRow.event_at < statement.excluded.event_at,
    )
    async with db.session() as session:
        await session.execute(statement)


async def record_deregistration(server_id: str, sent_at: datetime) -> bool:
    """The agent stopped. False when it never registered (or a newer announcement is applied)."""
    statement = (
        update(AgentRow)
        .where(AgentRow.server_id == server_id, AgentRow.event_at < sent_at)
        .values(deregistered_at=sent_at, event_at=sent_at)
    )
    async with db.session() as session:
        result = await session.execute(statement)
    return result.rowcount > 0


async def list_agents() -> list[Agent]:
    async with db.session() as session:
        rows = (await session.scalars(select(AgentRow).order_by(AgentRow.server_id))).all()
    return [_agent(row) for row in rows]


async def get_agent(server_id: str) -> Agent | None:
    async with db.session() as session:
        row = await session.get(AgentRow, server_id)
    return _agent(row) if row is not None else None


async def registered_server_ids() -> set[str]:
    """Servers whose agent announced itself and did not say goodbye."""
    async with db.session() as session:
        ids = await session.scalars(select(AgentRow.server_id).where(AgentRow.deregistered_at.is_(None)))
        return set(ids.all())


async def save_packages(server_id: str, snapshot: dict, sent_at: datetime) -> None:
    statement = insert(ServerPackagesRow).values(server_id=server_id, snapshot=snapshot, sent_at=sent_at)
    statement = statement.on_conflict_do_update(
        index_elements=[ServerPackagesRow.server_id],
        set_={"snapshot": statement.excluded.snapshot, "sent_at": statement.excluded.sent_at},
        where=ServerPackagesRow.sent_at < statement.excluded.sent_at,
    )
    async with db.session() as session:
        await session.execute(statement)


async def packages_of(server_id: str) -> dict | None:
    async with db.session() as session:
        row = await session.get(ServerPackagesRow, server_id)
    return dict(row.snapshot) if row is not None else None


async def save_db_snapshot(server_id: str, db_type: str, connections: list, sent_at: datetime) -> None:
    statement = insert(DBSnapshotRow).values(
        server_id=server_id, db_type=db_type, connections=connections, sent_at=sent_at,
    )
    statement = statement.on_conflict_do_update(
        index_elements=[DBSnapshotRow.server_id, DBSnapshotRow.db_type],
        set_={"connections": statement.excluded.connections, "sent_at": statement.excluded.sent_at},
        where=DBSnapshotRow.sent_at < statement.excluded.sent_at,
    )
    async with db.session() as session:
        await session.execute(statement)


@dataclass(frozen=True)
class DBSnapshot:
    db_type: str
    connections: list
    sent_at: datetime


async def db_snapshots_of(server_id: str) -> list[DBSnapshot]:
    statement = select(DBSnapshotRow).where(DBSnapshotRow.server_id == server_id).order_by(DBSnapshotRow.db_type)
    async with db.session() as session:
        rows = (await session.scalars(statement)).all()
    return [DBSnapshot(row.db_type, list(row.connections), row.sent_at) for row in rows]
