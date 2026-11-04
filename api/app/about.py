"""What is installed: Maestro's version and notes, the database, and each agent's version."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.config import settings
from app.release import VERSION, releases

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/about", tags=["about"])


class ReleaseOut(BaseModel):
    version: str
    date: str
    notes: dict[str, list[str]]


class AgentOut(BaseModel):
    server_id: str
    version: str
    last_seen: str | None


class AboutOut(BaseModel):
    version: str
    clickhouse_version: str | None
    agents: list[AgentOut]
    releases: list[ReleaseOut]


async def _clickhouse_version(client) -> str | None:
    try:
        result = await client.query("SELECT version()")
        return str(result.result_rows[0][0])
    except Exception as exc:
        logger.warning("about: could not read the ClickHouse version: %s", exc)
        return None


async def _agents(redis) -> list[AgentOut]:
    """From the heartbeat state every agent keeps fresh."""
    raw = await redis.hgetall(settings.heartbeat_state_key)
    agents = []
    for server_id, value in sorted(raw.items()):
        try:
            state = json.loads(value)
        except json.JSONDecodeError:
            continue
        agents.append(AgentOut(
            server_id=server_id,
            version=state.get("agent_version") or "unknown",
            last_seen=state.get("last_seen"),
        ))
    return agents


@router.get("", response_model=AboutOut)
async def get_about(request: Request) -> AboutOut:
    state = request.app.state
    return AboutOut(
        version=VERSION,
        clickhouse_version=await _clickhouse_version(state.ch_client),
        agents=await _agents(state.vuln_redis),
        releases=[ReleaseOut(version=r.version, date=r.date, notes=r.notes) for r in releases()],
    )
