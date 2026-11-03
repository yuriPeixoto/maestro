"""Rules every server gets when it first shows up, so none goes unwatched.

The limits are the ones behind a server's state (app.health_status), so a
default rule fires exactly when the dashboard turns the matching colour. A
server is handled once: rules deleted afterwards are not created again.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import redis.asyncio as aioredis

from app.clickhouse import AlertRule, ClickHouseReader, ClickHouseWriter
from app.config import settings
from app.health_status import cpu_limits, disk_limits, memory_limits
from app.rule_values import HEARTBEAT_AGE_METRIC

logger = logging.getLogger(__name__)

_OFFLINE_COOLDOWN_MINUTES = 5
_RESOURCE_COOLDOWN_MINUTES = 15
_DISK_COOLDOWN_MINUTES = 60


@dataclass(frozen=True)
class _Template:
    metric_name: str
    operator: str
    threshold: float
    severity: str
    cooldown_minutes: int


def _templates() -> list[_Template]:
    return [
        _Template(HEARTBEAT_AGE_METRIC, ">", float(settings.offline_threshold_seconds), "critical",
                  _OFFLINE_COOLDOWN_MINUTES),
        _Template("disk_usage_percent", ">=", disk_limits().attention, "warning", _DISK_COOLDOWN_MINUTES),
        _Template("disk_usage_percent", ">=", disk_limits().critical, "critical", _DISK_COOLDOWN_MINUTES),
        _Template("memory_usage_percent", ">=", memory_limits().critical, "critical", _RESOURCE_COOLDOWN_MINUTES),
        # Judged on the 5-minute average (SUSTAINED_METRICS), so a burst does not fire it.
        _Template("cpu_usage_percent", ">=", cpu_limits().critical, "critical", _RESOURCE_COOLDOWN_MINUTES),
    ]


def default_rules(server_id: str, now: datetime) -> list[AlertRule]:
    return [
        AlertRule(
            rule_id=uuid4(), server_id=server_id, metric_name=t.metric_name,
            operator=t.operator, threshold=t.threshold, severity=t.severity,
            cooldown_minutes=t.cooldown_minutes, enabled=True, created_at=now,
        )
        for t in _templates()
    ]


async def ensure_default_rules(
    server_id: str,
    reader: ClickHouseReader,
    writer: ClickHouseWriter,
    redis: aioredis.Redis,
) -> bool:
    """Give a server seen for the first time the default rules, if it has none. Return True if created."""
    if await redis.sismember(settings.default_rules_applied_key, server_id):
        return False

    created = False
    if not await reader.get_alert_rules(server_id):
        for rule in default_rules(server_id, datetime.now(timezone.utc)):
            await writer.insert_alert_rule(rule)
        logger.info("default_rules: created %d rules for %s", len(_templates()), server_id)
        created = True
    await redis.sadd(settings.default_rules_applied_key, server_id)
    return created
