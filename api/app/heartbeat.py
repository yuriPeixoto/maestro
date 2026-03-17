import asyncio
import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.config import settings
from app.consumer import _ensure_group

logger = logging.getLogger(__name__)

# Redis hash structure:
#   key:   maestro:server_heartbeats
#   field: server_id
#   value: JSON { "last_seen": "<ISO8601 UTC>", "agent_version": "<str>" }


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_heartbeat(raw: str) -> dict | None:
    """Parse the heartbeat payload emitted by the Go agent.

    Expected shape:
        {"server_id": "hostname", "timestamp": "2026-03-09T12:00:00Z", "agent_version": "dev"}
    """
    try:
        data = json.loads(raw)
        ts_raw = data["timestamp"].replace("Z", "+00:00")
        last_seen = datetime.fromisoformat(ts_raw).astimezone(timezone.utc)
        return {
            "server_id": data["server_id"],
            "last_seen": last_seen.isoformat(),
            "agent_version": data.get("agent_version", "unknown"),
        }
    except Exception as exc:
        logger.warning("heartbeat: failed to parse payload: %s — raw: %.200s", exc, raw)
        return None


async def run_heartbeat_consumer() -> None:
    """Reads from the heartbeat Redis stream and updates server last_seen state.

    State is stored in a Redis hash so reads are O(1) per server.
    Runs as an asyncio background task alongside the metrics consumer.
    """
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    try:
        await _ensure_group(
            redis,
            settings.heartbeat_stream,
            settings.heartbeat_consumer_group,
        )
        logger.info(
            "heartbeat: listening on '%s' (group='%s')",
            settings.heartbeat_stream,
            settings.heartbeat_consumer_group,
        )

        while True:
            try:
                results = await redis.xreadgroup(
                    groupname=settings.heartbeat_consumer_group,
                    consumername=settings.heartbeat_consumer_name,
                    streams={settings.heartbeat_stream: ">"},
                    count=100,
                    block=10_000,  # 10s block — heartbeats arrive every 30s
                )
            except aioredis.RedisError as exc:
                logger.error("heartbeat: redis error: %s — retrying in 5s", exc)
                await asyncio.sleep(5)
                continue

            if not results:
                continue

            _stream, messages = results[0]
            msg_ids = []

            for msg_id, fields in messages:
                parsed = _parse_heartbeat(fields.get("data", ""))
                if parsed:
                    await redis.hset(
                        settings.heartbeat_state_key,
                        parsed["server_id"],
                        json.dumps({
                            "last_seen": parsed["last_seen"],
                            "agent_version": parsed["agent_version"],
                        }),
                    )
                    logger.debug(
                        "heartbeat: updated server_id='%s' last_seen=%s",
                        parsed["server_id"],
                        parsed["last_seen"],
                    )
                msg_ids.append(msg_id)

            if msg_ids:
                await redis.xack(
                    settings.heartbeat_stream,
                    settings.heartbeat_consumer_group,
                    *msg_ids,
                )

    except asyncio.CancelledError:
        logger.info("heartbeat: shutting down")
    finally:
        await redis.aclose()
