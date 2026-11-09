"""The default rules: global ones, so no server goes unwatched, and editable like any rule.

The limits are the ones behind a server's state (app.health_status), so a default rule
fires exactly when the dashboard turns the matching colour. They are stored once
(app.alert_store.adopt_global_defaults): deleting one afterwards does not bring it back,
and a server overrides one with its own rule for the same metric and severity.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from app import alert_store
from app.alert_store import AlertRule
from app.config import settings
from app.health_status import cpu_limits, disk_limits, memory_limits
from app.rule_scope import SCOPE_GLOBAL, SCOPE_SERVER
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


def default_rules(server_id: str | None, now: datetime) -> list[AlertRule]:
    """The default rules, global (server_id None) or as one server's own copies."""
    return [
        AlertRule(
            rule_id=uuid4(), server_id=server_id, metric_name=t.metric_name,
            operator=t.operator, threshold=t.threshold, severity=t.severity,
            cooldown_minutes=t.cooldown_minutes, created_at=now,
            scope=SCOPE_SERVER if server_id is not None else SCOPE_GLOBAL,
        )
        for t in _templates()
    ]


async def ensure_global_default_rules() -> bool:
    """Store the default rules as global ones the first time. Return True if stored now."""
    created = await alert_store.adopt_global_defaults(default_rules(None, datetime.now(timezone.utc)))
    if created:
        logger.info("default_rules: stored %d global rules", len(_templates()))
    return created
