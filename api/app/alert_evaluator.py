"""Judges every alert rule each cycle and notifies on a change of state.

Rules and their state live in Postgres (app.alert_store). A change is applied with a
compare-and-set on the state's version before anything is sent, so an alert fires
once even if two evaluators judge it. Only the evaluator holding the advisory lock
works; another one stands by. The event then goes to the ClickHouse history; if that
insert fails the alert is still delivered, because a notification matters more than
a history row.
"""
from __future__ import annotations

import asyncio
import logging
import operator as op
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

import redis.asyncio as aioredis

from app import alert_store, db
from app.alert_store import STATE_FIRING, STATE_RESOLVED, AlertRule, AlertState
from app.clickhouse import AlertEvent, ClickHouseReader, ClickHouseWriter
from app.config import settings
from app.default_rules import ensure_default_rules
from app.delivery import KIND_FIRING, KIND_RESOLVED, Notification
from app.notification_dispatcher import dispatch_all
from app.notification_text import alert_text
from app.rule_values import current_rule_value

logger = logging.getLogger(__name__)

EVAL_INTERVAL_SECONDS = 30

# Advisory lock key of the evaluator ("maestro" + 0x01): one evaluator works at a time.
EVALUATOR_LOCK_KEY = 0x6D61657374726F01

_OPERATORS: dict[str, Callable[[float, float], bool]] = {
    ">":  op.gt,
    "<":  op.lt,
    ">=": op.ge,
    "<=": op.le,
    "==": op.eq,
}


async def run_alert_evaluator(
    reader: ClickHouseReader,
    writer: ClickHouseWriter,
    on_cycle: Callable[[], None] = lambda: None,
) -> None:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
    lock = db.AdvisoryLock(EVALUATOR_LOCK_KEY)
    standing_by = False
    try:
        logger.info("alert_evaluator: started (interval=%ds)", EVAL_INTERVAL_SECONDS)
        while True:
            await asyncio.sleep(EVAL_INTERVAL_SECONDS)
            try:
                if not await lock.hold():
                    if not standing_by:
                        logger.warning("alert_evaluator: another evaluator holds the lock; standing by")
                        standing_by = True
                    on_cycle()
                    continue
                if standing_by:
                    logger.info("alert_evaluator: took the lock; evaluating")
                    standing_by = False
                await _evaluate_all(reader, writer, redis)
            except Exception as exc:
                logger.error("alert_evaluator: evaluation cycle failed: %s", exc)
                continue
            on_cycle()
    finally:
        await lock.release()
        await redis.aclose()


async def _evaluate_all(reader: ClickHouseReader, writer: ClickHouseWriter, redis: aioredis.Redis) -> None:
    server_ids: list[str] = await redis.hkeys(settings.heartbeat_state_key)
    if not server_ids:
        return
    handled = await alert_store.servers_with_defaults()
    for server_id in server_ids:
        if server_id not in handled:
            await ensure_default_rules(server_id)
    for item in await alert_store.rules_to_evaluate(server_ids):
        try:
            await _evaluate_rule(item.rule, item.state, reader, writer, redis)
        except Exception as exc:
            logger.error("alert_evaluator: rule %s failed: %s", item.rule.rule_id, exc)


async def _is_breached(rule: AlertRule, value: float, reader: ClickHouseReader) -> bool | None:
    compare = _OPERATORS.get(rule.operator)
    if compare is None:
        logger.warning("alert_evaluator: unknown operator %r in rule %s", rule.operator, rule.rule_id)
        return None

    mode = rule.alert_mode or "static"
    static_breached = compare(value, rule.threshold) if mode in ("static", "both") else False
    ml_breached = False
    if mode in ("ml", "both"):
        score = await reader.get_latest_anomaly_score(rule.server_id, rule.metric_name)
        if score is not None:
            ml_breached = score >= rule.ml_score_threshold
        elif mode == "ml":
            # No score available: judge on the threshold instead.
            static_breached = compare(value, rule.threshold)
    return static_breached or ml_breached


def _in_cooldown(rule: AlertRule, state: AlertState, now: datetime) -> bool:
    """Do not fire again too soon after the last resolution."""
    if state.last_resolved_at is None:
        return False
    elapsed_minutes = (now - state.last_resolved_at).total_seconds() / 60
    return elapsed_minutes < rule.cooldown_minutes


async def _evaluate_rule(
    rule: AlertRule,
    state: AlertState,
    reader: ClickHouseReader,
    writer: ClickHouseWriter,
    redis: aioredis.Redis,
) -> None:
    value = await current_rule_value(reader, redis, rule.server_id, rule.metric_name)
    if value is None:
        return
    breached = await _is_breached(rule, value, reader)
    if breached is None:
        return

    now = datetime.now(timezone.utc)
    if breached and state.state != STATE_FIRING:
        if _in_cooldown(rule, state, now):
            return
        new = AlertState(state=STATE_FIRING, last_fired_at=now, last_resolved_at=state.last_resolved_at)
        kind = KIND_FIRING
    elif not breached and state.state == STATE_FIRING:
        new = AlertState(state=STATE_RESOLVED, last_fired_at=state.last_fired_at, last_resolved_at=now)
        kind = KIND_RESOLVED
    else:
        return

    event = AlertEvent(
        event_id=uuid4(), rule_id=rule.rule_id, server_id=rule.server_id,
        metric_name=rule.metric_name, value=value, threshold=rule.threshold,
        severity=rule.severity, state=new.state, triggered_at=now,
    )
    if not await alert_store.change_state(rule.rule_id, state, new, event.event_id):
        logger.info("alert_evaluator: rule %s changed elsewhere; skipping", rule.rule_id)
        return

    logger.info(
        "alert: %s rule=%s server=%s metric=%s value=%.2f %s %.2f",
        new.state, rule.rule_id, rule.server_id, rule.metric_name, value, rule.operator, rule.threshold,
    )
    try:
        await writer.insert_alert_event(event)
    except Exception:
        logger.exception("alert_evaluator: event %s of rule %s left out of the history", event.event_id, rule.rule_id)
    await _notify(event, kind, writer)


# Deliveries run beside the evaluation so a slow channel does not hold the cycle.
# The set keeps a reference until each one finishes.
_deliveries: set[asyncio.Task] = set()


async def _notify(event: AlertEvent, kind: str, writer: ClickHouseWriter) -> None:
    channels = await alert_store.channels_for_alert(event.server_id, event.rule_id)
    if not channels:
        return
    notification = Notification(kind=kind, server_id=event.server_id, text=alert_text(event), event=event)
    task = asyncio.create_task(dispatch_all(channels, notification, writer))
    _deliveries.add(task)
    task.add_done_callback(_deliveries.discard)
