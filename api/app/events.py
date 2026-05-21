from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.clickhouse import ClickHouseReader, ClickHouseWriter, ServerEvent
from app.logs import _utc_iso

router = APIRouter(prefix="/events", tags=["events"])


class ServerEventIn(BaseModel):
    event_type: str
    label: str
    metadata: dict = {}
    occurred_at: datetime | None = None


class ServerEventOut(BaseModel):
    event_id: str
    server_id: str
    event_type: str
    label: str
    metadata: dict
    occurred_at: str


@router.post("/{server_id}", response_model=ServerEventOut, status_code=201)
async def register_event(server_id: str, body: ServerEventIn, request: Request) -> ServerEventOut:
    import json as _json
    writer: ClickHouseWriter = request.app.state.ch_writer
    occurred_at = body.occurred_at or datetime.now(timezone.utc)
    event = ServerEvent(
        event_id=uuid4(),
        server_id=server_id,
        event_type=body.event_type,
        label=body.label,
        metadata=_json.dumps(body.metadata),
        occurred_at=occurred_at,
    )
    await writer.insert_server_event(event)
    return ServerEventOut(
        event_id=str(event.event_id),
        server_id=event.server_id,
        event_type=event.event_type,
        label=event.label,
        metadata=body.metadata,
        occurred_at=_utc_iso(occurred_at),
    )


@router.get("/{server_id}", response_model=list[ServerEventOut])
async def list_events(
    server_id: str,
    request: Request,
    limit: int = 100,
    event_type: str | None = None,
) -> list[ServerEventOut]:
    import json as _json
    reader: ClickHouseReader = request.app.state.ch_reader
    events = await reader.get_server_events(server_id, limit=limit, event_type=event_type)
    return [
        ServerEventOut(
            event_id=str(e.event_id),
            server_id=e.server_id,
            event_type=e.event_type,
            label=e.label,
            metadata=_json.loads(e.metadata) if e.metadata else {},
            occurred_at=_utc_iso(e.occurred_at),
        )
        for e in events
    ]
