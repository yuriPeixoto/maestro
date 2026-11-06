"""Alert rules, channels and alert state, in Postgres (ADR-011).

Functions return the plain dataclasses below, so routers and the evaluator do not
depend on the ORM. Deleting a rule or a channel sets deleted_at; deleted rows are
never returned. What happened (events, deliveries) stays in ClickHouse.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import AlertChannelRow, AlertDefaultsApplied, AlertRuleRow, AlertStateRow

STATE_INACTIVE = "INACTIVE"
STATE_FIRING = "FIRING"
STATE_RESOLVED = "RESOLVED"


@dataclass
class AlertRule:
    rule_id: UUID
    server_id: str
    metric_name: str
    operator: str
    threshold: float
    severity: str
    cooldown_minutes: int
    created_at: datetime
    alert_mode: str = "static"        # static | ml | both
    ml_score_threshold: float = 0.7   # used when alert_mode in ('ml', 'both')


@dataclass
class AlertChannel:
    channel_id: UUID
    rule_id: UUID | None   # None: every rule of the server
    server_id: str
    channel_type: str      # 'webhook' | 'email' | 'slack' | 'telegram'
    config: dict
    created_at: datetime


@dataclass
class AlertState:
    state: str = STATE_INACTIVE
    last_fired_at: datetime | None = None
    last_resolved_at: datetime | None = None
    last_event_id: UUID | None = None
    # None: no row yet. A change applies only while this is still the stored version.
    version: int | None = None


@dataclass
class RuleToEvaluate:
    rule: AlertRule
    state: AlertState = field(default_factory=AlertState)


class DuplicateRule(Exception):
    """The server already has an active rule with the same metric, operator, threshold and severity."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rule(row: AlertRuleRow) -> AlertRule:
    return AlertRule(
        rule_id=row.rule_id, server_id=row.server_id, metric_name=row.metric_name,
        operator=row.operator, threshold=row.threshold, severity=row.severity,
        cooldown_minutes=row.cooldown_minutes, created_at=row.created_at,
        alert_mode=row.alert_mode, ml_score_threshold=row.ml_score_threshold,
    )


def _channel(row: AlertChannelRow) -> AlertChannel:
    return AlertChannel(
        channel_id=row.channel_id, rule_id=row.rule_id, server_id=row.server_id,
        channel_type=row.channel_type, config=dict(row.config), created_at=row.created_at,
    )


def _state(row: AlertStateRow | None) -> AlertState:
    if row is None:
        return AlertState()
    return AlertState(
        state=row.state, last_fired_at=row.last_fired_at, last_resolved_at=row.last_resolved_at,
        last_event_id=row.last_event_id, version=row.version,
    )


def _rule_values(rule: AlertRule) -> dict:
    return {
        "rule_id": rule.rule_id, "server_id": rule.server_id, "metric_name": rule.metric_name,
        "operator": rule.operator, "threshold": rule.threshold, "severity": rule.severity,
        "cooldown_minutes": rule.cooldown_minutes, "alert_mode": rule.alert_mode,
        "ml_score_threshold": rule.ml_score_threshold, "created_at": rule.created_at,
    }


_ACTIVE_RULE = AlertRuleRow.deleted_at.is_(None)
_ACTIVE_CHANNEL = AlertChannelRow.deleted_at.is_(None)


# ── Rules ─────────────────────────────────────────────────────────────────────

async def list_rules(server_id: str) -> list[AlertRule]:
    async with db.session() as s:
        rows = await s.scalars(
            select(AlertRuleRow)
            .where(AlertRuleRow.server_id == server_id, _ACTIVE_RULE)
            .order_by(AlertRuleRow.created_at, AlertRuleRow.rule_id)
        )
        return [_rule(r) for r in rows]


async def rule_exists(server_id: str, rule_id: UUID) -> bool:
    async with db.session() as s:
        return bool(await s.scalar(select(exists().where(
            AlertRuleRow.rule_id == rule_id, AlertRuleRow.server_id == server_id, _ACTIVE_RULE,
        ))))


async def create_rule(rule: AlertRule) -> AlertRule:
    """Store a rule with its INACTIVE state. Raises DuplicateRule for a rule the server already has."""
    try:
        async with db.session() as s:
            await s.execute(insert(AlertRuleRow).values(**_rule_values(rule)))
            await s.execute(insert(AlertStateRow).values(rule_id=rule.rule_id))
    except IntegrityError as exc:
        if "alert_rules_active_unique" in str(exc.orig):
            raise DuplicateRule from None
        raise
    return rule


async def delete_rule(server_id: str, rule_id: UUID) -> bool:
    """Delete a rule and the channels that only served it. False when there is no such rule."""
    now = _now()
    async with db.session("alert_rules.delete") as s:
        deleted = await s.scalar(
            update(AlertRuleRow)
            .where(AlertRuleRow.rule_id == rule_id, AlertRuleRow.server_id == server_id, _ACTIVE_RULE)
            .values(deleted_at=now)
            .returning(AlertRuleRow.rule_id)
        )
        if deleted is None:
            return False
        await s.execute(
            update(AlertChannelRow)
            .where(AlertChannelRow.rule_id == rule_id, _ACTIVE_CHANNEL)
            .values(deleted_at=now)
        )
    return True


# ── Channels ──────────────────────────────────────────────────────────────────

async def list_channels(server_id: str) -> list[AlertChannel]:
    async with db.session() as s:
        rows = await s.scalars(
            select(AlertChannelRow)
            .where(AlertChannelRow.server_id == server_id, _ACTIVE_CHANNEL)
            .order_by(AlertChannelRow.rule_id.nulls_first(), AlertChannelRow.created_at)
        )
        return [_channel(r) for r in rows]


async def get_channel(server_id: str, channel_id: UUID) -> AlertChannel | None:
    async with db.session() as s:
        row = await s.scalar(select(AlertChannelRow).where(
            AlertChannelRow.channel_id == channel_id, AlertChannelRow.server_id == server_id, _ACTIVE_CHANNEL,
        ))
        return _channel(row) if row else None


async def channels_for_alert(server_id: str, rule_id: UUID) -> list[AlertChannel]:
    """Channels of this rule plus the channels that take every rule of the server."""
    async with db.session() as s:
        rows = await s.scalars(
            select(AlertChannelRow)
            .where(
                AlertChannelRow.server_id == server_id,
                or_(AlertChannelRow.rule_id == rule_id, AlertChannelRow.rule_id.is_(None)),
                _ACTIVE_CHANNEL,
            )
            .order_by(AlertChannelRow.created_at)
        )
        return [_channel(r) for r in rows]


async def create_channel(channel: AlertChannel) -> AlertChannel:
    async with db.session() as s:
        await s.execute(insert(AlertChannelRow).values(
            channel_id=channel.channel_id, server_id=channel.server_id, rule_id=channel.rule_id,
            channel_type=channel.channel_type, config=channel.config, created_at=channel.created_at,
        ))
    return channel


async def delete_channel(server_id: str, channel_id: UUID) -> bool:
    async with db.session("alert_channels.delete") as s:
        deleted = await s.scalar(
            update(AlertChannelRow)
            .where(AlertChannelRow.channel_id == channel_id, AlertChannelRow.server_id == server_id, _ACTIVE_CHANNEL)
            .values(deleted_at=_now())
            .returning(AlertChannelRow.channel_id)
        )
    return deleted is not None


# ── State ─────────────────────────────────────────────────────────────────────

async def rules_to_evaluate(server_ids: list[str]) -> list[RuleToEvaluate]:
    """Every active rule of these servers with where it stands, in one query."""
    if not server_ids:
        return []
    async with db.session() as s:
        rows = await s.execute(
            select(AlertRuleRow, AlertStateRow)
            .outerjoin(AlertStateRow, AlertStateRow.rule_id == AlertRuleRow.rule_id)
            .where(AlertRuleRow.server_id.in_(server_ids), _ACTIVE_RULE)
            .order_by(AlertRuleRow.server_id, AlertRuleRow.created_at)
        )
        return [RuleToEvaluate(_rule(rule), _state(state)) for rule, state in rows]


async def change_state(rule_id: UUID, read: AlertState, new: AlertState, event_id: UUID) -> bool:
    """Apply a change only if the state is still the one `read` saw (compare and set).

    False means another evaluator changed it first: the caller must not notify.
    """
    values = {
        "state": new.state,
        "last_fired_at": new.last_fired_at,
        "last_resolved_at": new.last_resolved_at,
        "last_event_id": event_id,
    }
    async with db.session() as s:
        if read.version is None:
            changed = await s.scalar(
                insert(AlertStateRow)
                .values(rule_id=rule_id, version=1, **values)
                .on_conflict_do_nothing(index_elements=["rule_id"])
                .returning(AlertStateRow.rule_id)
            )
        else:
            changed = await s.scalar(
                update(AlertStateRow)
                .where(AlertStateRow.rule_id == rule_id, AlertStateRow.version == read.version)
                .values(version=AlertStateRow.version + 1, **values)
                .returning(AlertStateRow.rule_id)
            )
    return changed is not None


async def firing_severities(server_id: str) -> dict[str, str]:
    """{rule_id: severity} of the server's active rules that are firing now."""
    async with db.session() as s:
        rows = await s.execute(
            select(AlertRuleRow.rule_id, AlertRuleRow.severity)
            .join(AlertStateRow, AlertStateRow.rule_id == AlertRuleRow.rule_id)
            .where(AlertRuleRow.server_id == server_id, _ACTIVE_RULE, AlertStateRow.state == STATE_FIRING)
        )
        return {str(rule_id): severity for rule_id, severity in rows}


# ── Default rules ─────────────────────────────────────────────────────────────

async def servers_with_defaults() -> set[str]:
    async with db.session() as s:
        return set(await s.scalars(select(AlertDefaultsApplied.server_id)))


async def apply_default_rules(server_id: str, rules: list[AlertRule]) -> bool:
    """Mark the server handled and, if it has no rules, store these. True if they were stored.

    One transaction: two evaluators cannot both create them, and a server is handled once,
    so rules deleted afterwards are not created again.
    """
    async with db.session() as s:
        first_time = await s.scalar(
            insert(AlertDefaultsApplied)
            .values(server_id=server_id)
            .on_conflict_do_nothing(index_elements=["server_id"])
            .returning(AlertDefaultsApplied.server_id)
        )
        if first_time is None:
            return False
        has_rules = await s.scalar(select(exists().where(and_(AlertRuleRow.server_id == server_id, _ACTIVE_RULE))))
        if has_rules:
            return False
        for rule in rules:
            await s.execute(insert(AlertRuleRow).values(**_rule_values(rule)))
            await s.execute(insert(AlertStateRow).values(rule_id=rule.rule_id))
    return True
