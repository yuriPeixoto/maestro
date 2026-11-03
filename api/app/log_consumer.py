from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.clickhouse import ClickHouseWriter, LogRow
from app.config import settings
from app.stream_reader import Message, StreamSpec, consume_stream

logger = logging.getLogger(__name__)

_LOG_BATCH_SIZE = 500
_LOG_BLOCK_MS = 5000


def _parse_log_event(fields: dict) -> LogRow | None:
    try:
        ts_raw = fields["timestamp"].replace("Z", "+00:00")
        ts_raw = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], ts_raw)
        timestamp = datetime.fromisoformat(ts_raw).astimezone(timezone.utc)
        return LogRow(
            server_id=fields["server_id"],
            log_file=fields["log_file"],
            timestamp=timestamp,
            line=fields["line"],
        )
    except Exception as exc:
        logger.warning("log_consumer: failed to parse event: %s — fields: %s", exc, fields)
        return None


def log_batch_handler(writer: ClickHouseWriter):
    async def handle(messages: list[Message]) -> None:
        rows = [row for _, fields in messages if (row := _parse_log_event(fields)) is not None]
        await writer.insert_log_batch(rows)
        logger.debug("log_consumer: inserted %d rows from %d messages", len(rows), len(messages))

    return handle


async def run_log_consumer(writer: ClickHouseWriter, on_cycle: Callable[[], None] = lambda: None) -> None:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
    spec = StreamSpec(
        stream=settings.log_stream,
        group=settings.log_consumer_group,
        consumer=settings.log_consumer_name,
        count=_LOG_BATCH_SIZE,
        block_ms=_LOG_BLOCK_MS,
    )
    logger.info("log_consumer: listening on '%s' (group='%s')", spec.stream, spec.group)
    try:
        await consume_stream(redis, spec, log_batch_handler(writer), on_cycle)
    finally:
        await redis.aclose()
