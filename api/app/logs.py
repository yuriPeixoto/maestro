from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import heartbeats
from app.clickhouse import ClickHouseReader
from app.heartbeats import HeartbeatSource

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/logs", tags=["logs"])


def _utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        return dt.isoformat(timespec="milliseconds") + "Z"
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class LogFilesResponse(BaseModel):
    server_id: str
    log_files: list[str]


class LogLine(BaseModel):
    server_id: str
    log_file: str
    timestamp: str
    line: str


class LogHistoryResponse(BaseModel):
    server_id: str
    log_file: str
    lines: list[LogLine]


@router.get("/{server_id}", response_model=LogFilesResponse)
async def list_log_files(
    server_id: str, beats: HeartbeatSource = Depends(heartbeats.dependency),
) -> LogFilesResponse:
    """Return the list of log files being watched by an agent (from latest heartbeat)."""
    raw = await beats.get(server_id)

    if raw is None:
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")

    state = json.loads(raw)
    return LogFilesResponse(server_id=server_id, log_files=state.get("watched_logs") or [])


@router.get("/{server_id}/{log_file:path}/history", response_model=LogHistoryResponse)
async def log_history(
    server_id: str,
    log_file: str,
    request: Request,
    lines: int = Query(default=200, ge=1, le=2000),
) -> LogHistoryResponse:
    """Return the last N lines for a server/log-file combination."""
    reader: ClickHouseReader = request.app.state.ch_reader
    rows = await reader.get_log_history(server_id, log_file, lines)
    return LogHistoryResponse(
        server_id=server_id,
        log_file=log_file,
        lines=[
            LogLine(
                server_id=r.server_id,
                log_file=r.log_file,
                timestamp=_utc_iso(r.timestamp),
                line=r.line,
            )
            for r in rows
        ],
    )


@router.get("/{server_id}/{log_file:path}/stream")
async def stream_logs(server_id: str, log_file: str, request: Request) -> StreamingResponse:
    """SSE endpoint — streams new log lines in real-time by polling ClickHouse every second."""
    reader: ClickHouseReader = request.app.state.ch_reader

    async def event_generator():
        last_ts = datetime.now(timezone.utc).replace(tzinfo=None)
        while True:
            if await request.is_disconnected():
                break
            try:
                rows = await reader.get_logs_since(server_id, log_file, last_ts)
                for row in rows:
                    last_ts = row.timestamp
                    payload = json.dumps({
                        "server_id": row.server_id,
                        "log_file": row.log_file,
                        "timestamp": row.timestamp.isoformat() + "Z",
                        "line": row.line,
                    })
                    yield f"data: {payload}\n\n"
            except Exception as exc:
                logger.warning("stream_logs: query error: %s", exc)
            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
