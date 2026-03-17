import asyncio
import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.clickhouse import ClickHouseWriter, MetricRow
from app.config import settings

logger = logging.getLogger(__name__)


def _parse_metric(raw: str) -> MetricRow | None:
    try:
        data = json.loads(raw)
        ts_raw = data["timestamp"].replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(ts_raw).astimezone(timezone.utc).replace(tzinfo=None)
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


async def _ensure_group(redis: aioredis.Redis, stream: str, group: str) -> None:
    try:
        await redis.xgroup_create(name=stream, groupname=group, id="$", mkstream=True)
        logger.info("consumer: created group '%s' on stream '%s'", group, stream)
    except aioredis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def run_consumer(writer: ClickHouseWriter) -> None:
    """Reads from the metrics Redis stream and writes batches to ClickHouse."""
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    try:
        await _ensure_group(redis, settings.redis_stream, settings.redis_consumer_group)
        logger.info(
            "consumer: listening on '%s' (group='%s', batch=%d)",
            settings.redis_stream, settings.redis_consumer_group, settings.consumer_batch_size,
        )

        while True:
            try:
                results = await redis.xreadgroup(
                    groupname=settings.redis_consumer_group,
                    consumername=settings.redis_consumer_name,
                    streams={settings.redis_stream: ">"},
                    count=settings.consumer_batch_size,
                    block=settings.consumer_flush_interval_ms,
                )
            except aioredis.RedisError as exc:
                logger.error("consumer: redis error: %s — retrying in 5s", exc)
                await asyncio.sleep(5)
                continue

            if not results:
                continue

            _stream, messages = results[0]
            rows, msg_ids = [], []

            for msg_id, fields in messages:
                row = _parse_metric(fields.get("data", ""))
                if row is not None:
                    rows.append(row)
                msg_ids.append(msg_id)

            if rows:
                await writer.insert_batch(rows)

            if msg_ids:
                await redis.xack(settings.redis_stream, settings.redis_consumer_group, *msg_ids)
                logger.debug("consumer: acked %d, inserted %d rows", len(msg_ids), len(rows))

    except asyncio.CancelledError:
        logger.info("consumer: shutting down")
    finally:
        await redis.aclose()