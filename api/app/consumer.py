from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.clickhouse import ClickHouseWriter, MetricRow
from app.config import settings
from app.stream_reader import Message, StreamSpec, consume_stream

logger = logging.getLogger(__name__)


def _parse_metric(raw: str) -> MetricRow | None:
    try:
        data = json.loads(raw)
        ts_raw = data["timestamp"].replace("Z", "+00:00")
        ts_raw = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], ts_raw)
        timestamp = datetime.fromisoformat(ts_raw).astimezone(timezone.utc)
        return MetricRow(
            server_id=data["server_id"],
            metric_name=data["metric_name"],
            value=float(data["value"]),
            timestamp=timestamp,
            tags=data.get("tags") or {},
        )
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
        rows = [row for _, fields in messages if (row := _parse_metric(fields.get("data", ""))) is not None]
        await writer.insert_batch(rows)
        logger.debug("consumer: inserted %d rows from %d messages", len(rows), len(messages))

    return handle


async def run_consumer(writer: ClickHouseWriter, on_cycle: Callable[[], None] = lambda: None) -> None:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
    spec = metrics_spec()
    logger.info("consumer: listening on '%s' (group='%s', batch=%d)", spec.stream, spec.group, spec.count)
    try:
        await consume_stream(redis, spec, metric_batch_handler(writer), on_cycle)
    finally:
        await redis.aclose()
