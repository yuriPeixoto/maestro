from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.config import settings
from app.stream_reader import Message, StreamSpec, consume_stream

logger = logging.getLogger(__name__)

_HEARTBEAT_BATCH_SIZE = 100
_HEARTBEAT_BLOCK_MS = 10_000


def _parse_heartbeat(raw: str) -> dict | None:
    try:
        data = json.loads(raw)
        ts_raw = data["timestamp"].replace("Z", "+00:00")
        ts_raw = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], ts_raw)
        last_seen = datetime.fromisoformat(ts_raw).astimezone(timezone.utc)
        return {
            "server_id": data["server_id"],
            "last_seen": last_seen.isoformat(),
            "agent_version": data.get("agent_version", "unknown"),
            "watched_logs": data.get("watched_logs") or [],
            "inventory": data.get("inventory") or [],
        }
    except Exception as exc:
        logger.warning("heartbeat: failed to parse payload: %s — raw: %.200s", exc, raw)
        return None


def heartbeat_batch_handler(redis: aioredis.Redis):
    async def handle(messages: list[Message]) -> None:
        for _, fields in messages:
            parsed = _parse_heartbeat(fields.get("data", ""))
            if not parsed:
                continue
            await redis.hset(
                settings.heartbeat_state_key,
                parsed["server_id"],
                json.dumps({
                    "last_seen": parsed["last_seen"],
                    "agent_version": parsed["agent_version"],
                    "watched_logs": parsed["watched_logs"],
                    "inventory": parsed["inventory"],
                }),
            )
            logger.debug("heartbeat: updated '%s' last_seen=%s", parsed["server_id"], parsed["last_seen"])

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