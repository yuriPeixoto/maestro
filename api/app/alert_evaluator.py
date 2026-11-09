"""Judges every alert rule each cycle, and tells the channels what changed.

Rules and their state live in Postgres (app.alert_store); each server is judged by the
rules that win there (app.rule_scope). A rule is FIRING, NO_DATA (its metric stopped
arriving), or calm (INACTIVE, RESOLVED). A change of state is applied with a
compare-and-set on the state's version, then goes to the ClickHouse history; if that
insert fails the alert is still delivered, because a notification matters more than a
history row. Only the evaluator holding the advisory lock works; another stands by.

What the channels hear is decided apart from the state, against `notified_state` (what
they last heard):

- while a server is in maintenance or a silence covers the alert (app.quiet), nothing is
  sent; when the quiet ends, a state that changed meanwhile is announced, saying when;
- "no data" of a server that sends no heartbeat is not sent: "no signal" already says it;
- a firing alert nobody acknowledged repeats every `cooldown_minutes`;
- every line of one cycle for one server goes out as one message (app.alert_outbox).

Before a line is queued its `notified_state` is written with another compare-and-set, so
two evaluators never send it twice.
"""
from __future__ import annotations

import asyncio
import logging
import operator as op
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import redis.asyncio as aioredis

from app import alert_outbox, alert_store, db, maintenance, notification_retries, server_store
from app.alert_outbox import Outgoing
from app.alert_store import (
    STATE_FIRING,
    STATE_NO_DATA,
    STATE_RESOLVED,
    AlertRule,
    AlertState,
    RuleToEvaluate,
)
from app.clickhouse import AlertEvent, ClickHouseReader, ClickHouseWriter
from app.config import settings
from app.default_rules import ensure_global_default_rules
from app.delivery import KIND_DATA_BACK, KIND_FIRING, KIND_NO_DATA, KIND_REMINDER, KIND_RESOLVED, Line
from app.notification_text import alert_text, data_back_text, late_suffix, no_data_text, reminder_text
from app.quiet import QuietNow, quiet_now
from app.rule_values import HEARTBEAT_AGE_METRIC, current_rule_value, heartbeat_age_seconds

logger = logging.getLogger(__name__)

EVAL_INTERVAL_SECONDS = 30
MAINTENANCE_EXTEND_SECONDS = 3600
# A metric missing now is "no data" only if the server sent it in this lookback: one never
# collected (a typo in the rule, a metric this agent does not send) has nothing that stopped.
NO_DATA_LOOKBACK = timedelta(hours=24)

# Advisory lock key of the evaluator ("maestro" + 0x01): one evaluator works at a time.
EVALUATOR_LOCK_KEY = 0x6D61657374726F01

_OPERATORS: dict[str, Callable[[float, float], bool]] = {
    ">":  op.gt,
    "<":  op.lt,
    ">=": op.ge,
    "<=": op.le,
    "==": op.eq,
}

_CALM = "calm"


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


@dataclass
class _Cycle:
    """What every rule of one cycle shares, and the lines it collects for the channels."""
    quiet: QuietNow = field(default_factory=QuietNow)
    labels: dict[str, str] = field(default_factory=dict)
    # Servers whose heartbeat is older than the offline limit.
    offline: set[str] = field(default_factory=set)
    outgoing: list[Outgoing] = field(default_factory=list)


_last_extension: float | None = None


async def _extend_maintenance() -> None:
    """Keep the weekly windows' occurrences written ahead, at most once an hour."""
    global _last_extension
    now = time.monotonic()
    if _last_extension is not None and now - _last_extension < MAINTENANCE_EXTEND_SECONDS:
        return
    _last_extension = now
    added = await maintenance.extend_weekly_windows()
    if added:
        logger.info("alert_evaluator: %d maintenance occurrences written ahead", added)


async def _offline_servers(redis: aioredis.Redis, server_ids: list[str], now: datetime) -> set[str]:
    entries = await redis.hmget(settings.heartbeat_state_key, server_ids)
    offline = set()
    for server_id, raw in zip(server_ids, entries):
        age = heartbeat_age_seconds(raw, now)
        if age is None or age > settings.offline_threshold_seconds:
            offline.add(server_id)
    return offline


async def _evaluate_all(reader: ClickHouseReader, writer: ClickHouseWriter, redis: aioredis.Redis) -> None:
    server_ids: list[str] = await redis.hkeys(settings.heartbeat_state_key)
    if not server_ids:
        return
    await server_store.register_servers(server_ids)
    await ensure_global_default_rules()
    await _extend_maintenance()
    quiet, labels, offline = await asyncio.gather(
        quiet_now(), server_store.labels(server_ids), _offline_servers(redis, server_ids, _now()),
    )
    cycle = _Cycle(quiet, labels, offline)
    for item in await alert_store.rules_to_evaluate(server_ids):
        try:
            await _evaluate_rule(item, reader, writer, redis, cycle)
        except Exception as exc:
            logger.error("alert_evaluator: rule %s on %s failed: %s", item.rule.rule_id, item.server_id, exc)
    alert_outbox.send_soon(cycle.outgoing, writer, cycle.labels)
    notification_retries.run_soon(writer)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Judging ───────────────────────────────────────────────────────────────────

async def _is_breached(rule: AlertRule, server_id: str, value: float, reader: ClickHouseReader) -> bool | None:
    compare = _OPERATORS.get(rule.operator)
    if compare is None:
        logger.warning("alert_evaluator: unknown operator %r in rule %s", rule.operator, rule.rule_id)
        return None

    mode = rule.alert_mode or "static"
    static_breached = compare(value, rule.threshold) if mode in ("static", "both") else False
    ml_breached = False
    if mode in ("ml", "both"):
        # An episode open for at least 5 minutes, not one anomalous minute (ADR-014).
        score = await reader.get_open_episode_score(server_id, rule.metric_name)
        if score is not None:
            ml_breached = score >= rule.ml_score_threshold
        elif mode == "ml" and await reader.get_latest_anomaly_score(server_id, rule.metric_name) is None:
            # The anomaly job has no recent score for this metric: judge on the threshold instead.
            static_breached = compare(value, rule.threshold)
    return static_breached or ml_breached


def _in_cooldown(rule: AlertRule, state: AlertState, now: datetime) -> bool:
    """Do not fire again too soon after the last resolution."""
    if state.last_resolved_at is None:
        return False
    elapsed_minutes = (now - state.last_resolved_at).total_seconds() / 60
    return elapsed_minutes < rule.cooldown_minutes


async def _target_state(
    rule: AlertRule, state: AlertState, server_id: str, value: float | None, reader: ClickHouseReader, now: datetime,
) -> str | None:
    """The state the rule should move to now, or None to leave it as it is."""
    if value is None:
        # No heartbeat entry at all says nothing: the "no signal" rule judges the age.
        if rule.metric_name == HEARTBEAT_AGE_METRIC or state.state == STATE_NO_DATA:
            return None
        if not await reader.has_metric_since(server_id, rule.metric_name, now - NO_DATA_LOOKBACK):
            return None
        return STATE_NO_DATA

    breached = await _is_breached(rule, server_id, value, reader)
    if breached is None:
        return None
    if breached:
        if state.state == STATE_FIRING or _in_cooldown(rule, state, now):
            return None
        return STATE_FIRING
    if state.state in (STATE_FIRING, STATE_NO_DATA):
        return STATE_RESOLVED
    return None


def _moved(state: AlertState, target: str, now: datetime) -> AlertState:
    fired = now if target == STATE_FIRING else state.last_fired_at
    resolved = now if target == STATE_RESOLVED and state.state == STATE_FIRING else state.last_resolved_at
    return replace(state, state=target, last_fired_at=fired, last_resolved_at=resolved)


def _event(rule: AlertRule, server_id: str, value: float | None, state: str, at: datetime, event_id=None) -> AlertEvent:
    return AlertEvent(
        event_id=event_id or uuid4(), rule_id=rule.rule_id, server_id=server_id,
        metric_name=rule.metric_name, value=value if value is not None else 0.0, threshold=rule.threshold,
        severity=rule.severity, state=state, triggered_at=at,
    )


async def _evaluate_rule(
    item: RuleToEvaluate,
    reader: ClickHouseReader,
    writer: ClickHouseWriter,
    redis: aioredis.Redis,
    cycle: _Cycle | None = None,
) -> None:
    cycle = cycle or _Cycle()
    rule, state, server_id = item.rule, item.state, item.server_id
    now = _now()
    value = await current_rule_value(reader, redis, server_id, rule.metric_name)
    target = await _target_state(rule, state, server_id, value, reader, now)

    event = None
    if target is not None:
        new = _moved(state, target, now)
        event = _event(rule, server_id, value, target, now)
        version = await alert_store.change_state(rule.rule_id, server_id, state, new, event.event_id, at=now)
        if version is None:
            logger.info("alert_evaluator: rule %s on %s changed elsewhere; skipping", rule.rule_id, server_id)
            return
        logger.info(
            "alert: %s rule=%s server=%s metric=%s value=%s %s %.2f",
            target, rule.rule_id, server_id, rule.metric_name,
            "none" if value is None else f"{value:.2f}", rule.operator, rule.threshold,
        )
        try:
            await writer.insert_alert_event(event)
        except Exception:
            logger.exception("alert_evaluator: event %s of rule %s left out of the history", event.event_id, rule.rule_id)
        opened_or_closed = state.is_open != new.is_open
        state = replace(
            new, version=version, changed_at=now, last_event_id=event.event_id,
            acknowledged_at=None if opened_or_closed else state.acknowledged_at,
            acknowledged_by=None if opened_or_closed else state.acknowledged_by,
        )

    await _announce(item, state, value, event, cycle, now)


# ── Announcing ────────────────────────────────────────────────────────────────

def _heard(state: str | None) -> str:
    """What a state means to a reader of the chat: firing, no data, or calm."""
    return state if state in (STATE_FIRING, STATE_NO_DATA) else _CALM


def _change_kind(told: str, now_is: str) -> str:
    if now_is == STATE_FIRING:
        return KIND_FIRING
    if now_is == STATE_NO_DATA:
        return KIND_NO_DATA
    return KIND_RESOLVED if told == STATE_FIRING else KIND_DATA_BACK


def _change_text(kind: str, event: AlertEvent, label: str | None) -> str:
    if kind == KIND_NO_DATA:
        return no_data_text(event, label)
    if kind == KIND_DATA_BACK:
        return data_back_text(event, label)
    return alert_text(event, label)


def _reminder_due(rule: AlertRule, state: AlertState, now: datetime) -> bool:
    if rule.cooldown_minutes <= 0 or state.acknowledged or state.last_notified_at is None:
        return False
    return now - state.last_notified_at >= timedelta(minutes=rule.cooldown_minutes)


def _line(
    item: RuleToEvaluate, state: AlertState, value: float | None, event: AlertEvent | None, cycle: _Cycle,
    now: datetime,
) -> tuple[Line, str] | None:
    """The line the channels should get about this alert now, and the state it tells them."""
    rule, server_id = item.rule, item.server_id
    if state.last_event_id is None:
        return None
    label = cycle.labels.get(server_id)
    told, now_is = _heard(state.notified_state), _heard(state.state)
    if event is None:
        # Nothing changed in this cycle: the line is about the alert as it stands.
        event = _event(rule, server_id, value, state.state, state.changed_at or now, event_id=state.last_event_id)

    if now_is != told:
        kind = _change_kind(told, now_is)
        text = _change_text(kind, event, label)
        if state.changed_at is not None and state.changed_at < now:
            text += late_suffix((now - state.changed_at).total_seconds())
        return Line(kind, text, event), state.state
    if state.state == STATE_FIRING and _reminder_due(rule, state, now):
        open_since = state.last_fired_at or state.changed_at or now
        return Line(KIND_REMINDER, reminder_text(event, (now - open_since).total_seconds(), label), event), STATE_FIRING
    return None


async def _announce(
    item: RuleToEvaluate, state: AlertState, value: float | None, event: AlertEvent | None, cycle: _Cycle,
    now: datetime,
) -> None:
    rule, server_id = item.rule, item.server_id
    quiet_reason = cycle.quiet.reason(server_id, item.group_id, rule.rule_id)
    if quiet_reason is not None:
        if event is not None:
            logger.info("alert_evaluator: %s of rule %s on %s not sent (%s)", event.state, rule.rule_id, server_id, quiet_reason)
        return
    if state.state == STATE_NO_DATA and server_id in cycle.offline:
        return
    found = _line(item, state, value, event, cycle, now)
    if found is None:
        return
    line, telling = found
    if state.version is None:
        return
    if await alert_store.mark_notified(rule.rule_id, server_id, state.version, telling, now) is None:
        logger.info("alert_evaluator: rule %s on %s announced elsewhere; skipping", rule.rule_id, server_id)
        return
    cycle.outgoing.append(Outgoing(line, item.group_id))

