from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.clickhouse import ClickHouseWriter, LogRow
from app.config import settings
from app.consumer import _ensure_group

logger = logging.getLogger(__name__)


def _parse_log_event(fields: dict) -> LogRow | None:
    try:
        ts_raw = fields["timestamp"].replace("Z", "+00:00")
        ts_raw = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], ts_raw)
        timestamp = datetime.fromisoformat(ts_raw).astimezone(timezone.utc).replace(tzinfo=None)
        return LogRow(
            server_id=fields["server_id"],
            log_file=fields["log_file"],
            timestamp=timestamp,
            line=fields["line"],
        )
    except Exception as exc:
        logger.warning("log_consumer: failed to parse event: %s — fields: %s", exc, fields)
        return None


async def run_log_consumer(writer: ClickHouseWriter) -> None:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await _ensure_group(redis, settings.log_stream, settings.log_consumer_group)
        logger.info("log_consumer: listening on '%s' (group='%s')", settings.log_stream, settings.log_consumer_group)

        while True:
            try:
                results = await redis.xreadgroup(
                    groupname=settings.log_consumer_group,
                    consumername=settings.log_consumer_name,
                    streams={settings.log_stream: ">"},
                    count=500,
                    block=5000,
                )
            except aioredis.RedisError as exc:
                logger.error("log_consumer: redis error: %s — retrying in 5s", exc)
                await asyncio.sleep(5)
                continue

            if not results:
                continue

            _stream, messages = results[0]
            rows, msg_ids = [], []
            for msg_id, fields in messages:
                row = _parse_log_event(fields)
                if row is not None:
                    rows.append(row)
                msg_ids.append(msg_id)

            if rows:
                await writer.insert_log_batch(rows)
            if msg_ids:
                await redis.xack(settings.log_stream, settings.log_consumer_group, *msg_ids)
                logger.debug("log_consumer: acked %d, inserted %d rows", len(msg_ids), len(rows))

    except asyncio.CancelledError:
        logger.info("log_consumer: shutting down")
    finally:
        await redis.aclose()
