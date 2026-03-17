import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/servers", tags=["servers"])


class ServerStatus(BaseModel):
    server_id: str
    status: str
    last_seen: str | None
    agent_version: str | None


async def get_redis() -> aioredis.Redis:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield redis
    finally:
        await redis.aclose()


def _resolve_status(last_seen_iso: str | None) -> str:
    if last_seen_iso is None:
        return "unknown"
    try:
        last_seen = datetime.fromisoformat(last_seen_iso)
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last_seen).total_seconds()
        return "online" if elapsed <= settings.offline_threshold_seconds else "offline"
    except ValueError:
        return "unknown"


def _build_server_status(server_id: str, raw_json: str | None) -> ServerStatus:
    if raw_json is None:
        return ServerStatus(server_id=server_id, status="unknown", last_seen=None, agent_version=None)
    try:
        data = json.loads(raw_json)
        last_seen = data.get("last_seen")
        return ServerStatus(
            server_id=server_id,
            status=_resolve_status(last_seen),
            last_seen=last_seen,
            agent_version=data.get("agent_version"),
        )
    except (json.JSONDecodeError, KeyError):
        return ServerStatus(server_id=server_id, status="unknown", last_seen=None, agent_version=None)


@router.get("", response_model=list[ServerStatus])
async def list_servers(redis: aioredis.Redis = Depends(get_redis)):
    all_entries: dict[str, str] = await redis.hgetall(settings.heartbeat_state_key)
    return [_build_server_status(sid, raw) for sid, raw in all_entries.items()]


@router.get("/{server_id}/status", response_model=ServerStatus)
async def get_server_status(server_id: str, redis: aioredis.Redis = Depends(get_redis)):
    raw: str | None = await redis.hget(settings.heartbeat_state_key, server_id)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")
    return _build_server_status(server_id, raw)