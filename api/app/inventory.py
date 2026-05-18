from __future__ import annotations

import json

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.servers import get_redis

router = APIRouter(prefix="/inventory", tags=["inventory"])


class RuntimeEntry(BaseModel):
    name: str
    version: str
    status: str
    uptime_since: str | None = None


class InventoryResponse(BaseModel):
    server_id: str
    inventory: list[RuntimeEntry]


@router.get("/{server_id}", response_model=InventoryResponse)
async def get_inventory(server_id: str, redis: aioredis.Redis = Depends(get_redis)) -> InventoryResponse:
    raw: str | None = await redis.hget(settings.heartbeat_state_key, server_id)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found")

    data = json.loads(raw)
    entries = [RuntimeEntry(**e) for e in data.get("inventory") or []]
    return InventoryResponse(server_id=server_id, inventory=entries)
