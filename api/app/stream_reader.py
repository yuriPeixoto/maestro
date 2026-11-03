"""Read a Redis Stream through a consumer group without losing messages.

A message is acked only after its batch was handled. When handling fails the
batch stays in the group's pending list (PEL) and is read again, with a growing
pause, before any new message. On startup the PEL is read first too, so
messages delivered before a crash are not left behind.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Stream ids for XREADGROUP: "0" re-reads this consumer's pending messages,
# ">" asks for messages never delivered to the group.
_PENDING = "0"
_NEW = ">"

_REDIS_ERROR_PAUSE_SECONDS = 5.0
_RETRY_BASE_DELAY_SECONDS = 1.0
_RETRY_MAX_DELAY_SECONDS = 60.0

Message = tuple[str, dict]
BatchHandler = Callable[[list[Message]], Awaitable[None]]


@dataclass(frozen=True)
class StreamSpec:
    stream: str
    group: str
    consumer: str
    count: int
    block_ms: int


async def ensure_group(redis: aioredis.Redis, stream: str, group: str) -> None:
    try:
        await redis.xgroup_create(name=stream, groupname=group, id="$", mkstream=True)
        logger.info("stream: created group '%s' on stream '%s'", group, stream)
    except aioredis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def consume_stream(
    redis: aioredis.Redis,
    spec: StreamSpec,
    handle: BatchHandler,
    on_cycle: Callable[[], None] = lambda: None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Loop forever: read a batch, hand it to `handle`, ack only if it returned.

    `on_cycle` runs after every cycle that left nothing behind (a batch acked or
    an empty read), so a caller can tell a working consumer from a stuck one.
    """
    await ensure_group(redis, spec.stream, spec.group)
    reading_pending = True
    retry_delay = _RETRY_BASE_DELAY_SECONDS

    while True:
        try:
            results = await redis.xreadgroup(
                groupname=spec.group,
                consumername=spec.consumer,
                streams={spec.stream: _PENDING if reading_pending else _NEW},
                count=spec.count,
                block=None if reading_pending else spec.block_ms,
            )
        except aioredis.RedisError as exc:
            logger.error("stream %s: redis error: %s — retrying in %.0fs", spec.stream, exc, _REDIS_ERROR_PAUSE_SECONDS)
            await sleep(_REDIS_ERROR_PAUSE_SECONDS)
            continue

        messages: list[Message] = results[0][1] if results else []
        if not messages:
            if reading_pending:
                reading_pending = False
                continue
            on_cycle()
            continue

        # A pending entry the stream already trimmed comes back with no fields.
        live = [(msg_id, fields) for msg_id, fields in messages if fields]
        try:
            if live:
                await handle(live)
        except Exception as exc:
            logger.error(
                "stream %s: batch of %d failed, kept pending, retrying in %.0fs: %s",
                spec.stream, len(live), retry_delay, exc,
            )
            reading_pending = True
            await sleep(retry_delay)
            retry_delay = min(retry_delay * 2, _RETRY_MAX_DELAY_SECONDS)
            continue

        await redis.xack(spec.stream, spec.group, *[msg_id for msg_id, _ in messages])
        retry_delay = _RETRY_BASE_DELAY_SECONDS
        on_cycle()
