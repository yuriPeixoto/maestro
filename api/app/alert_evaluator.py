from __future__ import annotations

import asyncio
import json
import logging
import operator as op
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

import redis.asyncio as aioredis

from app.clickhouse import (
    SERVER_WIDE_RULE_ID,
    AlertChannel,
    AlertEvent,
    AlertRule,
    ClickHouseReader,
    ClickHouseWriter,
)
from app.config import settings
from app.default_rules import ensure_default_rules
from app.delivery import KIND_FIRING, KIND_RESOLVED, Notification
from app.notification_dispatcher import dispatch_all
from app.notification_text import alert_text
from app.rule_values import current_rule_value

logger = logging.getLogger(__name__)

EVAL_INTERVAL_SECONDS = 30

_OPERATORS: dict[str, any] = {
    ">":  op.gt,
    "<":  op.lt,
    ">=": op.ge,
    "<=": op.le,
    "==": op.eq,
}

# Metric names that were renamed in the agent. Rules created before the rename
# will have the old names — migrate them transparently on startup.
_METRIC_ALIASES: dict[str, str] = {
    "cpu_percent":    "cpu_usage_percent",
    "memory_percent": "memory_usage_percent",
    "disk_percent":   "disk_usage_percent",
}


async def _migrate_legacy_metric_names(
    reader: ClickHouseReader, writer: ClickHouseWriter
) -> None:
    """Re-insert alert rules with outdated metric names using the corrected name.

    ReplacingMergeTree keeps the row with the highest version, so inserting a new
    version with the corrected metric_name effectively renames the rule without
    changing its rule_id or alert history.
    """
    server_ids: list[str] = await reader.get_known_server_ids()
    for server_id in server_ids:
        rules = await reader.get_alert_rules(server_id)
        for rule in rules:
            new_name = _METRIC_ALIASES.get(rule.metric_name)
            if new_name is None:
                continue
            corrected = AlertRule(
                rule_id=rule.rule_id, server_id=rule.server_id,
                metric_name=new_name, operator=rule.operator,
                threshold=rule.threshold, severity=rule.severity,
                cooldown_minutes=rule.cooldown_minutes, enabled=True,
                created_at=rule.created_at,
                alert_mode=rule.alert_mode,
                ml_score_threshold=rule.ml_score_threshold,
            )
            await writer.insert_alert_rule(corrected)
            logger.info(
                "alert_evaluator: migrated rule %s  %s → %s",
                rule.rule_id, rule.metric_name, new_name,
            )


async def run_alert_evaluator(
    reader: ClickHouseReader,
    writer: ClickHouseWriter,
    on_cycle: Callable[[], None] = lambda: None,
) -> None:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
    try:
        logger.info("alert_evaluator: started (interval=%ds)", EVAL_INTERVAL_SECONDS)
        await _migrate_legacy_metric_names(reader, writer)
        await _migrate_legacy_webhooks(redis, writer)
        while True:
            await asyncio.sleep(EVAL_INTERVAL_SECONDS)
            try:
                await _evaluate_all(reader, writer, redis)
            except Exception as exc:
                logger.error("alert_evaluator: evaluation cycle failed: %s", exc)
                continue
            on_cycle()
    finally:
        await redis.aclose()


async def _evaluate_all(reader: ClickHouseReader, writer: ClickHouseWriter, redis: aioredis.Redis) -> None:
    server_ids: list[str] = await redis.hkeys(settings.heartbeat_state_key)
    for server_id in server_ids:
        await ensure_default_rules(server_id, reader, writer, redis)
        rules = await reader.get_alert_rules(server_id)
        for rule in rules:
            try:
                await _evaluate_rule(rule, reader, writer, redis)
            except Exception as exc:
                logger.error("alert_evaluator: rule %s failed: %s", rule.rule_id, exc)


async def _evaluate_rule(
    rule: AlertRule,
    reader: ClickHouseReader,
    writer: ClickHouseWriter,
    redis: aioredis.Redis,
) -> None:
    value = await current_rule_value(reader, redis, rule.server_id, rule.metric_name)
    if value is None:
        return

    compare = _OPERATORS.get(rule.operator)
    if compare is None:
        logger.warning("alert_evaluator: unknown operator %r in rule %s", rule.operator, rule.rule_id)
        return

    mode = rule.alert_mode or "static"

    # Static threshold evaluation
    static_breached = compare(value, rule.threshold) if mode in ("static", "both") else False

    # ML score evaluation
    ml_breached = False
    if mode in ("ml", "both"):
        score = await reader.get_latest_anomaly_score(rule.server_id, rule.metric_name)
        if score is not None:
            ml_breached = score >= rule.ml_score_threshold
        elif mode == "ml":
            # Fallback: no model available — evaluate statically
            static_breached = compare(value, rule.threshold)

    breached = static_breached or ml_breached
    state_key = f"maestro:alert_state:{rule.server_id}:{rule.rule_id}"
    raw = await redis.get(state_key)
    current: dict = json.loads(raw) if raw else {
        "state": "INACTIVE",
        "last_fired_at": None,
        "last_resolved_at": None,
    }

    now = datetime.now(timezone.utc)

    if breached and current["state"] != "FIRING":
        # Cooldown check: don't re-fire if still within cooldown after last resolution.
        if current["last_resolved_at"]:
            last_resolved = datetime.fromisoformat(current["last_resolved_at"])
            elapsed_minutes = (now - last_resolved).total_seconds() / 60
            if elapsed_minutes < rule.cooldown_minutes:
                return

        event = AlertEvent(
            event_id=uuid4(), rule_id=rule.rule_id, server_id=rule.server_id,
            metric_name=rule.metric_name, value=value, threshold=rule.threshold,
            severity=rule.severity, state="FIRING", triggered_at=now,
        )
        await writer.insert_alert_event(event)
        await redis.set(state_key, json.dumps({
            "state": "FIRING",
            "last_fired_at": now.isoformat(),
            "last_resolved_at": current["last_resolved_at"],
        }))
        logger.info(
            "alert: FIRING rule=%s server=%s metric=%s value=%.2f %s %.2f",
            rule.rule_id, rule.server_id, rule.metric_name, value, rule.operator, rule.threshold,
        )
        await _notify(event, KIND_FIRING, reader, writer)

    elif not breached and current["state"] == "FIRING":
        event = AlertEvent(
            event_id=uuid4(), rule_id=rule.rule_id, server_id=rule.server_id,
            metric_name=rule.metric_name, value=value, threshold=rule.threshold,
            severity=rule.severity, state="RESOLVED", triggered_at=now,
        )
        await writer.insert_alert_event(event)
        await redis.set(state_key, json.dumps({
            "state": "RESOLVED",
            "last_fired_at": current["last_fired_at"],
            "last_resolved_at": now.isoformat(),
        }))
        logger.info(
            "alert: RESOLVED rule=%s server=%s metric=%s value=%.2f",
            rule.rule_id, rule.server_id, rule.metric_name, value,
        )
        await _notify(event, KIND_RESOLVED, reader, writer)


# Deliveries run beside the evaluation so a slow channel does not hold the cycle.
# The set keeps a reference until each one finishes.
_deliveries: set[asyncio.Task] = set()


async def _notify(event: AlertEvent, kind: str, reader: ClickHouseReader, writer: ClickHouseWriter) -> None:
    channels = await reader.get_channels_for_alert(event.server_id, event.rule_id)
    if not channels:
        return
    notification = Notification(kind=kind, server_id=event.server_id, text=alert_text(event), event=event)
    task = asyncio.create_task(dispatch_all(channels, notification, writer))
    _deliveries.add(task)
    task.add_done_callback(_deliveries.discard)


_LEGACY_WEBHOOK_PATTERN = "maestro:webhook:*"


async def _migrate_legacy_webhooks(redis: aioredis.Redis, writer: ClickHouseWriter) -> None:
    """Turn each per-server webhook kept in Redis into a server-wide channel, once."""
    async for key in redis.scan_iter(match=_LEGACY_WEBHOOK_PATTERN):
        url = await redis.get(key)
        server_id = key.removeprefix(_LEGACY_WEBHOOK_PATTERN[:-1])
        if url:
            await writer.insert_alert_channel(AlertChannel(
                channel_id=uuid4(), rule_id=SERVER_WIDE_RULE_ID, server_id=server_id,
                channel_type="webhook", config=json.dumps({"url": url}),
                enabled=True, created_at=datetime.now(timezone.utc),
            ))
            logger.info("alert_evaluator: moved the legacy webhook of %s into its channels", server_id)
        await redis.delete(key)
