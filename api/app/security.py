from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.clickhouse import ClickHouseReader, SshStats
from app.logs import _utc_iso

router = APIRouter(prefix="/security", tags=["security"])

# ── Regex patterns ─────────────────────────────────────────────────────────────

_FAILED = re.compile(r"Failed password for (?:invalid user )?(\S+) from (\S+) port")
_INVALID = re.compile(r"Invalid user (\S+) from (\S+)")
_ACCEPTED = re.compile(r"Accepted (?:publickey|password) for (\S+) from (\S+)")
_CLOSED = re.compile(r"Connection closed by (?:authenticating user |invalid user )?(\S+) (\S+) port")


def _classify(ts: str, line: str) -> dict | None:
    m = _FAILED.search(line)
    if m:
        return {"timestamp": ts, "type": "SSH", "action": "Failed Login",
                "username": m.group(1), "source_ip": m.group(2), "result": "Blocked"}
    m = _INVALID.search(line)
    if m:
        return {"timestamp": ts, "type": "SSH", "action": "Invalid User",
                "username": m.group(1), "source_ip": m.group(2), "result": "Dropped"}
    m = _ACCEPTED.search(line)
    if m:
        return {"timestamp": ts, "type": "AUTH", "action": "Login Accepted",
                "username": m.group(1), "source_ip": m.group(2), "result": "Success"}
    m = _CLOSED.search(line)
    if m:
        return {"timestamp": ts, "type": "SSH", "action": "Connection Closed",
                "username": m.group(1), "source_ip": m.group(2), "result": "Dropped"}
    return None


# ── Response models ────────────────────────────────────────────────────────────

class SshEvent(BaseModel):
    timestamp: str
    type: str
    action: str
    username: str
    source_ip: str
    result: str


class SshStatsOut(BaseModel):
    attempts_1h: int
    attempts_24h: int
    unique_ips_24h: int
    top_target: str | None


class SshEventsResponse(BaseModel):
    server_id: str
    stats: SshStatsOut
    events: list[SshEvent]


# ── Route ──────────────────────────────────────────────────────────────────────

@router.get("/{server_id}/ssh-events", response_model=SshEventsResponse)
async def ssh_events(server_id: str, request: Request) -> SshEventsResponse:
    reader: ClickHouseReader = request.app.state.ch_reader

    raw_rows, stats = await _fetch(reader, server_id)

    events: list[SshEvent] = []
    for row in raw_rows:
        parsed = _classify(_utc_iso(row.timestamp), row.line)
        if parsed:
            events.append(SshEvent(**parsed))

    return SshEventsResponse(
        server_id=server_id,
        stats=SshStatsOut(
            attempts_1h=stats.attempts_1h,
            attempts_24h=stats.attempts_24h,
            unique_ips_24h=stats.unique_ips_24h,
            top_target=stats.top_target,
        ),
        events=events,
    )


async def _fetch(reader: ClickHouseReader, server_id: str):
    import asyncio
    from app.clickhouse import LogRow

    rows_result, stats = await asyncio.gather(
        reader.get_log_history(server_id, "auth.log", 200),
        reader.get_ssh_stats(server_id),
    )
    return rows_result, stats
