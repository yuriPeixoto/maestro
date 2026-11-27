"""Metrics from the Redis stream `maestro:metrics` into ClickHouse (the transport until 1.0.0).

The agent writes one entry per metric, with the id of the batch it came in (`msg_id`); entries
whose batch already arrived through NATS are dropped (app.dedup).
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app import dedup
from app.clickhouse import ClickHouseWriter, MetricRow
from app.config import settings
from app.stream_reader import Message, StreamSpec, consume_stream

logger = logging.getLogger(__name__)

_FRACTION = re.compile(r"\.(\d+)")


def parse_agent_timestamp(raw: str) -> datetime:
    """The agent's RFC 3339 timestamps, with up to nanoseconds, as an aware UTC datetime."""
    normalized = raw.replace("Z", "+00:00")
    normalized = _FRACTION.sub(lambda m: "." + (m.group(1) + "000000")[:6], normalized)
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)


def parse_metric(data: dict) -> MetricRow:
    """Raises on a metric that is missing a field or has one of the wrong type."""
    return MetricRow(
        server_id=data["server_id"],
        metric_name=data["metric_name"],
        value=float(data["value"]),
        timestamp=parse_agent_timestamp(data["timestamp"]),
        tags=data.get("tags") or {},
    )


def _parse_metric(raw: str) -> MetricRow | None:
    try:
        return parse_metric(json.loads(raw))
    except Exception as exc:
        logger.warning("consumer: failed to parse metric: %s — raw: %.200s", exc, raw)
        return None


def metrics_spec() -> StreamSpec:
    return StreamSpec(
        stream=settings.redis_stream,
        group=settings.redis_consumer_group,
        consumer=settings.redis_consumer_name,
        count=settings.consumer_batch_size,
        block_ms=settings.consumer_flush_interval_ms,
    )


def metric_batch_handler(writer: ClickHouseWriter):
    async def handle(messages: list[Message]) -> None:
        # A message that cannot be parsed never will be: it is acked with the batch.
        items = [
            (dedup.parse_id(fields.get("msg_id")), [row])
            for _, fields in messages
            if (row := _parse_metric(fields.get("data", ""))) is not None
        ]
        written = await dedup.write_once(items, "redis", "metrics", writer.insert_batch)
        logger.debug("consumer: inserted %d rows from %d messages", written, len(messages))

    return handle


async def run_consumer(writer: ClickHouseWriter, on_cycle: Callable[[], None] = lambda: None) -> None:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
    spec = metrics_spec()
    logger.info("consumer: listening on '%s' (group='%s', batch=%d)", spec.stream, spec.group, spec.count)
    try:
        await consume_stream(redis, spec, metric_batch_handler(writer), on_cycle)
    finally:
        await redis.aclose()
