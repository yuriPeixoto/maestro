"""The value an alert rule is judged on.

Most rules read a metric from ClickHouse. `heartbeat_age_seconds` is not a
stored metric: it is the time since the server's last heartbeat, read from
Redis, so a server that stopped sending anything still trips its rule.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.clickhouse import ClickHouseReader
from app.config import settings

HEARTBEAT_AGE_METRIC = "heartbeat_age_seconds"


def heartbeat_age_seconds(raw_entry: str | None, now: datetime) -> float | None:
    """Seconds since the heartbeat stored in `raw_entry`, or None if it is unreadable."""
    if not raw_entry:
        return None
    try:
        last_seen = datetime.fromisoformat(json.loads(raw_entry)["last_seen"])
    except (ValueError, KeyError, TypeError):
        return None
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    return max((now - last_seen).total_seconds(), 0.0)


async def current_rule_value(
    reader: ClickHouseReader,
    redis: aioredis.Redis,
    server_id: str,
    metric_name: str,
) -> float | None:
    if metric_name == HEARTBEAT_AGE_METRIC:
        raw = await redis.hget(settings.heartbeat_state_key, server_id)
        return heartbeat_age_seconds(raw, datetime.now(timezone.utc))
    return await reader.get_status_metric_value(server_id, metric_name)
