from __future__ import annotations

import asyncio
import json
import logging
import operator as op
from datetime import datetime, timezone
from uuid import uuid4

import redis.asyncio as aioredis

from app.clickhouse import AlertEvent, AlertRule, ClickHouseReader, ClickHouseWriter
from app.config import settings

logger = logging.getLogger(__name__)

_EVAL_INTERVAL = 30  # seconds

_OPERATORS: dict[str, any] = {
    ">":  op.gt,
    "<":  op.lt,
    ">=": op.ge,
    "<=": op.le,
    "==": op.eq,
}


async def run_alert_evaluator(reader: ClickHouseReader, writer: ClickHouseWriter) -> None:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        logger.info("alert_evaluator: started (interval=%ds)", _EVAL_INTERVAL)
        while True:
            await asyncio.sleep(_EVAL_INTERVAL)
            try:
                await _evaluate_all(reader, writer, redis)
            except Exception as exc:
                logger.error("alert_evaluator: evaluation cycle failed: %s", exc)
    except asyncio.CancelledError:
        logger.info("alert_evaluator: shutting down")
    finally:
        await redis.aclose()


async def _evaluate_all(reader: ClickHouseReader, writer: ClickHouseWriter, redis: aioredis.Redis) -> None:
    server_ids: list[str] = await redis.hkeys(settings.heartbeat_state_key)
    for server_id in server_ids:
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
    value = await reader.get_latest_metric_value(rule.server_id, rule.metric_name)
    if value is None:
        return

    compare = _OPERATORS.get(rule.operator)
    if compare is None:
        logger.warning("alert_evaluator: unknown operator %r in rule %s", rule.operator, rule.rule_id)
        return

    breached = compare(value, rule.threshold)
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

        await writer.insert_alert_event(AlertEvent(
            event_id=uuid4(), rule_id=rule.rule_id, server_id=rule.server_id,
            metric_name=rule.metric_name, value=value, threshold=rule.threshold,
            severity=rule.severity, state="FIRING", triggered_at=now,
        ))
        await redis.set(state_key, json.dumps({
            "state": "FIRING",
            "last_fired_at": now.isoformat(),
            "last_resolved_at": current["last_resolved_at"],
        }))
        logger.info(
            "alert: FIRING rule=%s server=%s metric=%s value=%.2f %s %.2f",
            rule.rule_id, rule.server_id, rule.metric_name, value, rule.operator, rule.threshold,
        )

    elif not breached and current["state"] == "FIRING":
        await writer.insert_alert_event(AlertEvent(
            event_id=uuid4(), rule_id=rule.rule_id, server_id=rule.server_id,
            metric_name=rule.metric_name, value=value, threshold=rule.threshold,
            severity=rule.severity, state="RESOLVED", triggered_at=now,
        ))
        await redis.set(state_key, json.dumps({
            "state": "RESOLVED",
            "last_fired_at": current["last_fired_at"],
            "last_resolved_at": now.isoformat(),
        }))
        logger.info(
            "alert: RESOLVED rule=%s server=%s metric=%s value=%.2f",
            rule.rule_id, rule.server_id, rule.metric_name, value,
        )
