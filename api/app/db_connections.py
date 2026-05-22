from __future__ import annotations

import json
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.clickhouse import ClickHouseReader
from app.config import settings
from app.logs import _utc_iso

router = APIRouter(prefix="/db-connections", tags=["db-connections"])

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
    """Returns the latest connection snapshot for all monitored DBs on this server."""
    redis: aioredis.Redis = request.app.state.vuln_redis

    all_fields = await redis.hgetall(_SNAPSHOT_KEY)
    prefix = f"{server_id}:"
    snapshots: list[DBSnapshotResponse] = []

    now = datetime.now(timezone.utc).isoformat()
    for field, raw in all_fields.items():
        if not field.startswith(prefix):
            continue
        db_type = field[len(prefix):]
        try:
            conns = [DBConnection(**c) for c in json.loads(raw)]
        except Exception:
            conns = []
        snapshots.append(DBSnapshotResponse(
            server_id=server_id,
            db_type=db_type,
            captured_at=now,
            connections=conns,
        ))

    return DBSnapshotsResponse(server_id=server_id, snapshots=snapshots)


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
