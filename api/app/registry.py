from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    server_id: str
    hostname: str
    os: str
    tags: list[str] = []
    agent_version: str = "unknown"


class AgentInfo(BaseModel):
    server_id: str
    hostname: str
    os: str
    tags: list[str]
    agent_version: str
    registered_at: str
    last_seen: str | None
    status: str   # "online" | "offline" | "unknown"


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_redis() -> aioredis.Redis:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
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


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", status_code=200)
async def register_agent(
    body: RegisterRequest,
    redis: aioredis.Redis = Depends(_get_redis),
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "hostname": body.hostname,
        "os": body.os,
        "tags": json.dumps(body.tags),
        "agent_version": body.agent_version,
        "registered_at": now,
    }
    await redis.hset(f"{settings.registry_key}:{body.server_id}", mapping=payload)
    await redis.sadd(settings.agent_ids_key, body.server_id)
    logger.info("registry: registered server_id=%s hostname=%s", body.server_id, body.hostname)
    return {"registered": True, "server_id": body.server_id}


@router.delete("/{server_id}", status_code=200)
async def deregister_agent(
    server_id: str,
    redis: aioredis.Redis = Depends(_get_redis),
) -> dict:
    exists = await redis.exists(f"{settings.registry_key}:{server_id}")
    if not exists:
        raise HTTPException(status_code=404, detail=f"Agent '{server_id}' not registered")
    await redis.delete(f"{settings.registry_key}:{server_id}")
    await redis.srem(settings.agent_ids_key, server_id)
    logger.info("registry: deregistered server_id=%s", server_id)
    return {"deregistered": True, "server_id": server_id}


@router.get("", response_model=list[AgentInfo])
async def list_agents(redis: aioredis.Redis = Depends(_get_redis)) -> list[AgentInfo]:
    server_ids = await redis.smembers(settings.agent_ids_key)
    if not server_ids:
        return []

    agents = []
    for server_id in sorted(server_ids):
        reg = await redis.hgetall(f"{settings.registry_key}:{server_id}")
        if not reg:
            continue

        # Merge with heartbeat data for last_seen and status.
        hb_raw = await redis.hget(settings.heartbeat_state_key, server_id)
        last_seen = None
        if hb_raw:
            try:
                last_seen = json.loads(hb_raw).get("last_seen")
            except (json.JSONDecodeError, KeyError):
                pass

        agents.append(AgentInfo(
            server_id=server_id,
            hostname=reg.get("hostname", "unknown"),
            os=reg.get("os", "unknown"),
            tags=json.loads(reg.get("tags", "[]")),
            agent_version=reg.get("agent_version", "unknown"),
            registered_at=reg.get("registered_at", ""),
            last_seen=last_seen,
            status=_resolve_status(last_seen),
        ))

    return agents


@router.get("/{server_id}", response_model=AgentInfo)
async def get_agent(
    server_id: str,
    redis: aioredis.Redis = Depends(_get_redis),
) -> AgentInfo:
    reg = await redis.hgetall(f"{settings.registry_key}:{server_id}")
    if not reg:
        raise HTTPException(status_code=404, detail=f"Agent '{server_id}' not registered")

    hb_raw = await redis.hget(settings.heartbeat_state_key, server_id)
    last_seen = None
    if hb_raw:
        try:
            last_seen = json.loads(hb_raw).get("last_seen")
        except (json.JSONDecodeError, KeyError):
            pass

    return AgentInfo(
        server_id=server_id,
        hostname=reg.get("hostname", "unknown"),
        os=reg.get("os", "unknown"),
        tags=json.loads(reg.get("tags", "[]")),
        agent_version=reg.get("agent_version", "unknown"),
        registered_at=reg.get("registered_at", ""),
        last_seen=last_seen,
        status=_resolve_status(last_seen),
    )
