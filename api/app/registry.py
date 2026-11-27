"""The agent registry (`agents` in Postgres). An agent on NATS announces itself with an
`agent_registered` event on its own subject (app.nats_ingest); a user with the permission can also
register or remove one here. Last seen and status come from the server's heartbeat.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import agent_store, heartbeats
from app.agent_store import Agent
from app.auth import require
from app.config import settings
from app.heartbeats import HeartbeatSource
from app.permissions import Permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])

# Writes need a role that grants it (app.permissions); reads only a login.
_MANAGE_AGENTS = [Depends(require(Permission.MANAGE_AGENTS))]


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
    deregistered_at: str | None
    last_seen: str | None
    status: str   # "online" | "offline" | "unknown"


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _last_seen(raw_heartbeat: str | None) -> str | None:
    if not raw_heartbeat:
        return None
    try:
        return json.loads(raw_heartbeat).get("last_seen")
    except (json.JSONDecodeError, AttributeError):
        return None


def _info(agent: Agent, raw_heartbeat: str | None) -> AgentInfo:
    last_seen = _last_seen(raw_heartbeat)
    return AgentInfo(
        server_id=agent.server_id,
        hostname=agent.hostname,
        os=agent.os,
        tags=agent.tags,
        agent_version=agent.agent_version,
        registered_at=agent.registered_at.isoformat(),
        deregistered_at=agent.deregistered_at.isoformat() if agent.deregistered_at else None,
        last_seen=last_seen,
        status=_resolve_status(last_seen),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/register", status_code=200, dependencies=_MANAGE_AGENTS)
async def register_agent(body: RegisterRequest) -> dict:
    await agent_store.record_registration(
        body.server_id, body.hostname, body.os, body.tags, body.agent_version, datetime.now(timezone.utc),
    )
    logger.info("registry: registered server_id=%s hostname=%s", body.server_id, body.hostname)
    return {"registered": True, "server_id": body.server_id}


@router.delete("/{server_id}", status_code=200, dependencies=_MANAGE_AGENTS)
async def deregister_agent(server_id: str) -> dict:
    if not await agent_store.record_deregistration(server_id, datetime.now(timezone.utc)):
        raise HTTPException(status_code=404, detail=f"Agent '{server_id}' not registered")
    logger.info("registry: deregistered server_id=%s", server_id)
    return {"deregistered": True, "server_id": server_id}


@router.get("", response_model=list[AgentInfo])
async def list_agents(beats: HeartbeatSource = Depends(heartbeats.dependency)) -> list[AgentInfo]:
    agents = await agent_store.list_agents()
    states = await beats.get_many([agent.server_id for agent in agents])
    return [_info(agent, state) for agent, state in zip(agents, states)]


@router.get("/{server_id}", response_model=AgentInfo)
async def get_agent(server_id: str, beats: HeartbeatSource = Depends(heartbeats.dependency)) -> AgentInfo:
    agent = await agent_store.get_agent(server_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{server_id}' not registered")
    return _info(agent, await beats.get(server_id))
