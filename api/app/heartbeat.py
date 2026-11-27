"""Heartbeats from the Redis stream `maestro:heartbeat` into the `maestro:server_heartbeats` hash
(the transport until 1.0.0). On NATS nothing consumes them: the `MAESTRO_HEARTBEAT` stream keeps
each server's last one, read where it is needed (app.heartbeats).
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable

import redis.asyncio as aioredis

from app.config import settings
from app.consumer import parse_agent_timestamp
from app.stream_reader import Message, StreamSpec, consume_stream

logger = logging.getLogger(__name__)

_HEARTBEAT_BATCH_SIZE = 100
_HEARTBEAT_BLOCK_MS = 10_000


def heartbeat_state(data: dict) -> dict:
    """What is kept of a heartbeat, the JSON every heartbeat reader parses. Raises on a bad one."""
    return {
        "last_seen": parse_agent_timestamp(data["timestamp"]).isoformat(),
        "agent_version": data.get("agent_version", "unknown"),
        "watched_logs": data.get("watched_logs") or [],
        "inventory": data.get("inventory") or [],
    }


def _parse_heartbeat(raw: str) -> tuple[str, dict] | None:
    try:
        data = json.loads(raw)
        return data["server_id"], heartbeat_state(data)
    except Exception as exc:
        logger.warning("heartbeat: failed to parse payload: %s — raw: %.200s", exc, raw)
        return None


def heartbeat_batch_handler(redis: aioredis.Redis):
    async def handle(messages: list[Message]) -> None:
        for _, fields in messages:
            parsed = _parse_heartbeat(fields.get("data", ""))
            if not parsed:
                continue
            server_id, state = parsed
            await redis.hset(settings.heartbeat_state_key, server_id, json.dumps(state))
            logger.debug("heartbeat: updated '%s' last_seen=%s", server_id, state["last_seen"])

    return handle


async def run_heartbeat_consumer(on_cycle: Callable[[], None] = lambda: None) -> None:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
    spec = StreamSpec(
        stream=settings.heartbeat_stream,
        group=settings.heartbeat_consumer_group,
        consumer=settings.heartbeat_consumer_name,
        count=_HEARTBEAT_BATCH_SIZE,
        block_ms=_HEARTBEAT_BLOCK_MS,
    )
    logger.info("heartbeat: listening on '%s'", spec.stream)
    try:
        await consume_stream(redis, spec, heartbeat_batch_handler(redis), on_cycle)
    finally:
        await redis.aclose()
