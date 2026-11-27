from __future__ import annotations

import json
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import agent_store
from app.clickhouse import ClickHouseReader
from app.logs import _utc_iso

router = APIRouter(prefix="/db-connections", tags=["db-connections"])

# Written by an agent on Redis; an agent on NATS sends a db_connections event instead (db_snapshots).
_SNAPSHOT_KEY = "maestro:db_snapshots"


# ── Schemas ───────────────────────────────────────────────────────────────────

class DBConnection(BaseModel):
    user: str
    host: str
    db: str = ""
    command: str = ""
    state: str = ""
    elapsed_sec: int
    query: str = ""
    client: str = ""


class DBSnapshotResponse(BaseModel):
    server_id: str
    db_type: str
    captured_at: str
    connections: list[DBConnection]


class DBSnapshotsResponse(BaseModel):
    server_id: str
    snapshots: list[DBSnapshotResponse]


class DBHistoryPoint(BaseModel):
    timestamp: str
    total: float
    long_running: float


class DBHistoryResponse(BaseModel):
    server_id: str
    db_type: str
    data: list[DBHistoryPoint]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{server_id}", response_model=DBSnapshotsResponse)
async def get_db_snapshot(server_id: str, request: Request) -> DBSnapshotsResponse:
    """Returns the latest connection snapshot for all monitored DBs on this server: from the
    agent's db_connections events, and for the databases they do not cover, from Redis."""
    redis: aioredis.Redis = request.app.state.vuln_redis

    snapshots = [
        DBSnapshotResponse(
            server_id=server_id, db_type=s.db_type, captured_at=_utc_iso(s.sent_at),
            connections=_connections(s.connections),
        )
        for s in await agent_store.db_snapshots_of(server_id)
    ]
    covered = {s.db_type for s in snapshots}

    all_fields = await redis.hgetall(_SNAPSHOT_KEY)
    prefix = f"{server_id}:"
    now = datetime.now(timezone.utc).isoformat()
    for field, raw in all_fields.items():
        if not field.startswith(prefix) or field[len(prefix):] in covered:
            continue
        try:
            conns = _connections(json.loads(raw))
        except ValueError:
            conns = []
        snapshots.append(DBSnapshotResponse(
            server_id=server_id,
            db_type=field[len(prefix):],
            captured_at=now,
            connections=conns,
        ))

    return DBSnapshotsResponse(server_id=server_id, snapshots=snapshots)


def _connections(raw: list) -> list[DBConnection]:
    try:
        return [DBConnection(**c) for c in raw]
    except Exception:
        return []


@router.get("/{server_id}/history", response_model=DBHistoryResponse)
async def get_db_history(
    server_id: str,
    request: Request,
    db_type: str = "mysql",
    minutes: int = 60,
) -> DBHistoryResponse:
    """Returns time-series data for total and long-running connections."""
    reader: ClickHouseReader = request.app.state.ch_reader
    data = await reader.get_db_connection_history(server_id, db_type, minutes)
    return DBHistoryResponse(server_id=server_id, db_type=db_type, data=data)
