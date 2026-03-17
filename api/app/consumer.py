import asyncio
import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.clickhouse import ClickHouseWriter, MetricRow
from app.config import settings

logger = logging.getLogger(__name__)


def _parse_metric(raw: str) -> MetricRow | None:
    """Parse a JSON metric payload published by the Go agent.

    Expected shape:
        {
            "server_id":   "hostname",
            "metric_name": "cpu_usage_percent",
            "value":       42.5,
            "timestamp":   "2026-03-09T12:00:00Z",
            "tags":        {"device": "sda"}   // optional
        }
    """
    try:
        data = json.loads(raw)
        ts_raw = data["timestamp"]
        # Accept both RFC3339 with Z suffix and +00:00.
        ts_raw = ts_raw.replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(ts_raw).astimezone(timezone.utc).replace(tzinfo=None)
        return MetricRow(
            server_id=data["server_id"],
            metric_name=data["metric_name"],
            value=float(data["value"]),
            timestamp=timestamp,
            tags=data.get("tags") or {},
        )
    except Exception as exc:
        logger.warning("consumer: failed to parse metric payload: %s — raw: %.200s", exc, raw)
        return None


async def _ensure_consumer_group(redis: aioredis.Redis) -> None:
    """Create the consumer group if it does not exist.

    MKSTREAM creates the stream if it does not yet exist (e.g. agent hasn't
    started yet). Starting at '$' means we only consume new messages — we do
    not replay historical data on first boot.
    """
    try:
        await redis.xgroup_create(
            name=settings.redis_stream,
            groupname=settings.redis_consumer_group,
            id="$",
            mkstream=True,
        )
        logger.info(
            "consumer: created consumer group '%s' on stream '%s'",
            settings.redis_consumer_group,
            settings.redis_stream,
        )
    except aioredis.ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            # Group already exists — normal on restart.
            logger.debug("consumer: consumer group already exists, continuing")
        else:
            raise


async def run_consumer(writer: ClickHouseWriter) -> None:
    """Main consumer loop. Reads from Redis Streams, batches rows, writes to ClickHouse.

    Runs indefinitely — expected to be launched as an asyncio background task
    and cancelled on application shutdown.
    """
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    try:
        await _ensure_consumer_group(redis)
        logger.info(
            "consumer: listening on stream '%s' (group='%s', consumer='%s', batch=%d)",
            settings.redis_stream,
            settings.redis_consumer_group,
            settings.redis_consumer_name,
            settings.consumer_batch_size,
        )

        while True:
            try:
                # Block up to flush_interval_ms waiting for new messages.
                # '>' delivers only messages not yet assigned to any consumer in the group.
                results = await redis.xreadgroup(
                    groupname=settings.redis_consumer_group,
                    consumername=settings.redis_consumer_name,
                    streams={settings.redis_stream: ">"},
                    count=settings.consumer_batch_size,
                    block=settings.consumer_flush_interval_ms,
                )
            except aioredis.RedisError as exc:
                logger.error("consumer: redis read error: %s — retrying in 5s", exc)
                await asyncio.sleep(5)
                continue

            if not results:
                # Timeout with no messages — normal during low traffic.
                continue

            # results shape: [(stream_name, [(msg_id, {field: value}), ...])]
            _stream_name, messages = results[0]

            rows: list[MetricRow] = []
            msg_ids: list[str] = []

            for msg_id, fields in messages:
                raw = fields.get("data", "")
                row = _parse_metric(raw)
                if row is not None:
                    rows.append(row)
                msg_ids.append(msg_id)

            # Write to ClickHouse — insert_batch handles retries and drops on failure.
            if rows:
                await writer.insert_batch(rows)

            # Acknowledge all messages (including those that failed to parse).
            # This prevents them from being redelivered and blocking the stream.
            if msg_ids:
                await redis.xack(
                    settings.redis_stream,
                    settings.redis_consumer_group,
                    *msg_ids,
                )
                logger.debug(
                    "consumer: acked %d message(s), inserted %d row(s)",
                    len(msg_ids),
                    len(rows),
                )

    except asyncio.CancelledError:
        logger.info("consumer: shutting down")
    finally:
        await redis.aclose()