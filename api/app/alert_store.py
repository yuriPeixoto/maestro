"""Alert rules, channels and alert state, in Postgres (ADR-011, ADR-013).

A rule or channel belongs to a place: every server (`global`), a group or one server.
For each metric and severity the most specific rule wins (app.rule_scope); channels add
up. The state is kept per rule and server, because a global rule watches every server.

Functions return the plain dataclasses below, so routers and the evaluator do not
depend on the ORM. Deleting a rule or a channel sets deleted_at; deleted rows are
never returned. What happened (events, deliveries) stays in ClickHouse.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, exists, false, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app import db, rule_scope
from app.models import (
    AlertChannelRow,
    AlertDefaultsApplied,
    AlertRuleRow,
    AlertStateRow,
    ServerGroupRow,
    ServerRow,
    User,
)
from app.rule_scope import SCOPE_GLOBAL, SCOPE_GROUP, SCOPE_SERVER, Place

STATE_INACTIVE = "INACTIVE"
STATE_FIRING = "FIRING"
STATE_RESOLVED = "RESOLVED"
STATE_NO_DATA = "NO_DATA"
# States that leave an alert open: something to look at, and to acknowledge.
OPEN_STATES = frozenset({STATE_FIRING, STATE_NO_DATA})

# The values a rule may change; metric, severity and place are what it is.
EDITABLE_RULE_FIELDS = frozenset(
    {"operator", "threshold", "cooldown_minutes", "alert_mode", "ml_score_threshold", "enabled"},
)


@dataclass
class AlertRule:
    rule_id: UUID
    server_id: str | None   # None unless scope is 'server'
    metric_name: str
    operator: str
    threshold: float
    severity: str
    cooldown_minutes: int
    created_at: datetime
    alert_mode: str = "static"        # static | ml | both
    ml_score_threshold: float = 0.7   # used when alert_mode in ('ml', 'both')
    scope: str = SCOPE_SERVER
    group_id: int | None = None
    # False: the rule switches off the one it overrides, there and below.
    enabled: bool = True

    @property
    def place(self) -> Place:
        return Place(self.scope, self.server_id, self.group_id)


@dataclass
class AlertChannel:
    channel_id: UUID
    rule_id: UUID | None   # None: every rule
    server_id: str | None
    channel_type: str      # 'webhook' | 'email' | 'slack' | 'telegram'
    config: dict
    created_at: datetime
    scope: str = SCOPE_SERVER
    group_id: int | None = None

    @property
    def place(self) -> Place:
        return Place(self.scope, self.server_id, self.group_id)


@dataclass
class AlertState:
    state: str = STATE_INACTIVE
    last_fired_at: datetime | None = None
    last_resolved_at: datetime | None = None
    last_event_id: UUID | None = None
    # None: no row yet. A change applies only while this is still the stored version.
    version: int | None = None
    changed_at: datetime | None = None
    # What the channels last heard (None: nothing yet), and when.
    notified_state: str | None = None
    last_notified_at: datetime | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: int | None = None

    @property
    def is_open(self) -> bool:
        return self.state in OPEN_STATES

    @property
    def acknowledged(self) -> bool:
        return self.acknowledged_at is not None


@dataclass
class RuleToEvaluate:
    rule: AlertRule
    server_id: str
    group_id: int | None = None
    state: AlertState = field(default_factory=AlertState)


@dataclass
class ResolvedRule:
    """The rule that wins on a server for one metric and severity, and the ones it overrides."""
    rule: AlertRule
    overrides: list[AlertRule]


class DuplicateRule(Exception):
    """The place already has an active rule for the same metric and severity."""


class UnknownGroup(Exception):
    """The group does not exist or was deleted."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rule(row: AlertRuleRow) -> AlertRule:
    return AlertRule(
        rule_id=row.rule_id, server_id=row.server_id, metric_name=row.metric_name,
        operator=row.operator, threshold=row.threshold, severity=row.severity,
        cooldown_minutes=row.cooldown_minutes, created_at=row.created_at,
        alert_mode=row.alert_mode, ml_score_threshold=row.ml_score_threshold,
        scope=row.scope, group_id=row.group_id, enabled=row.enabled,
    )


def _channel(row: AlertChannelRow) -> AlertChannel:
    return AlertChannel(
        channel_id=row.channel_id, rule_id=row.rule_id, server_id=row.server_id,
        channel_type=row.channel_type, config=dict(row.config), created_at=row.created_at,
        scope=row.scope, group_id=row.group_id,
    )


def _state(row: AlertStateRow | None) -> AlertState:
    if row is None:
        return AlertState()
    return AlertState(
        state=row.state, last_fired_at=row.last_fired_at, last_resolved_at=row.last_resolved_at,
        last_event_id=row.last_event_id, version=row.version,
        changed_at=row.changed_at, notified_state=row.notified_state, last_notified_at=row.last_notified_at,
        acknowledged_at=row.acknowledged_at, acknowledged_by=row.acknowledged_by,
    )


def _rule_values(rule: AlertRule) -> dict:
    return {
        "rule_id": rule.rule_id, "scope": rule.scope, "server_id": rule.server_id, "group_id": rule.group_id,
        "metric_name": rule.metric_name, "operator": rule.operator, "threshold": rule.threshold,
        "severity": rule.severity, "cooldown_minutes": rule.cooldown_minutes, "alert_mode": rule.alert_mode,
        "ml_score_threshold": rule.ml_score_threshold, "enabled": rule.enabled, "created_at": rule.created_at,
    }


_ACTIVE_RULE = AlertRuleRow.deleted_at.is_(None)
_ACTIVE_CHANNEL = AlertChannelRow.deleted_at.is_(None)


def _at_place(model, place: Place):
    """Rows of exactly this place."""
    return and_(
        model.scope == place.scope,
        model.server_id.is_(None) if place.server_id is None else model.server_id == place.server_id,
        model.group_id.is_(None) if place.group_id is None else model.group_id == place.group_id,
    )


def _covering(model, server_id: str, group_id: int | None):
    """Rows whose place covers this server: global, its group, itself."""
    return or_(
        model.scope == SCOPE_GLOBAL,
        and_(model.scope == SCOPE_GROUP, model.group_id == group_id) if group_id is not None else false(),
        and_(model.scope == SCOPE_SERVER, model.server_id == server_id),
    )


async def group_of(server_id: str) -> int | None:
    async with db.session() as s:
        return await s.scalar(select(ServerRow.group_id).where(ServerRow.server_id == server_id))


async def _groups_of(server_ids: list[str]) -> dict[str, int | None]:
    async with db.session() as s:
        rows = await s.execute(select(ServerRow.server_id, ServerRow.group_id).where(ServerRow.server_id.in_(server_ids)))
        known = {server_id: group_id for server_id, group_id in rows}
    return {server_id: known.get(server_id) for server_id in server_ids}


# ── Rules ─────────────────────────────────────────────────────────────────────

async def list_rules(server_id: str) -> list[AlertRule]:
    """The rules set on this server itself (not the inherited ones)."""
    return await rules_at(Place(SCOPE_SERVER, server_id=server_id))


async def rules_at(place: Place) -> list[AlertRule]:
    async with db.session() as s:
        rows = await s.scalars(
            select(AlertRuleRow)
            .where(_at_place(AlertRuleRow, place), _ACTIVE_RULE)
            .order_by(AlertRuleRow.created_at, AlertRuleRow.rule_id)
        )
        return [_rule(r) for r in rows]


async def all_rules() -> list[AlertRule]:
    """Every active rule of every place."""
    async with db.session() as s:
        rows = await s.scalars(
            select(AlertRuleRow).where(_ACTIVE_RULE).order_by(AlertRuleRow.created_at, AlertRuleRow.rule_id)
        )
        return [_rule(r) for r in rows]


async def _rules_covering(server_ids: list[str], group_ids: set[int]) -> list[AlertRule]:
    async with db.session() as s:
        rows = await s.scalars(
            select(AlertRuleRow)
            .where(
                _ACTIVE_RULE,
                or_(
                    AlertRuleRow.scope == SCOPE_GLOBAL,
                    and_(AlertRuleRow.scope == SCOPE_GROUP, AlertRuleRow.group_id.in_(group_ids)),
                    and_(AlertRuleRow.scope == SCOPE_SERVER, AlertRuleRow.server_id.in_(server_ids)),
                ),
            )
            .order_by(AlertRuleRow.created_at, AlertRuleRow.rule_id)
        )
        return [_rule(r) for r in rows]


async def resolved_rules(server_id: str) -> list[ResolvedRule]:
    """What applies on this server, metric by metric, including rules switched off there."""
    group_id = await group_of(server_id)
    candidates = await _rules_covering([server_id], {group_id} if group_id is not None else set())
    return [ResolvedRule(rule, overrides) for rule, overrides in rule_scope.resolve(candidates, server_id, group_id)]


async def effective_rules(server_id: str) -> list[AlertRule]:
    """The rules judged on this server: the winners that are switched on."""
    return [item.rule for item in await resolved_rules(server_id) if item.rule.enabled]


async def get_rule(rule_id: UUID) -> AlertRule | None:
    async with db.session() as s:
        row = await s.scalar(select(AlertRuleRow).where(AlertRuleRow.rule_id == rule_id, _ACTIVE_RULE))
        return _rule(row) if row else None


async def rule_exists(server_id: str, rule_id: UUID) -> bool:
    """True when the rule applies on this server (set there or inherited)."""
    return any(rule.rule_id == rule_id for rule in await effective_rules(server_id))


def _integrity(exc: IntegrityError) -> Exception:
    message = str(exc.orig)
    if "alert_rules_active_unique" in message:
        return DuplicateRule()
    if "server_groups" in message or "group_id" in message:
        return UnknownGroup()
    return exc


async def create_rule(rule: AlertRule) -> AlertRule:
    """Store a rule. Raises DuplicateRule when its place has one for the same metric and
    severity, UnknownGroup for a group that does not exist."""
    try:
        async with db.session() as s:
            await _check_group(s, rule.group_id)
            await s.execute(insert(AlertRuleRow).values(**_rule_values(rule)))
            if rule.scope == SCOPE_SERVER:
                await s.execute(insert(AlertStateRow).values(rule_id=rule.rule_id, server_id=rule.server_id))
    except IntegrityError as exc:
        raise _integrity(exc) from None
    return rule


async def _check_group(s, group_id: int | None) -> None:
    if group_id is None:
        return
    found = await s.scalar(select(exists().where(
        ServerGroupRow.group_id == group_id, ServerGroupRow.deleted_at.is_(None),
    )))
    if not found:
        raise UnknownGroup()


async def update_rule(rule_id: UUID, changes: dict) -> AlertRule | None:
    """Change a rule's values (EDITABLE_RULE_FIELDS). None when there is no such rule."""
    unknown = set(changes) - EDITABLE_RULE_FIELDS
    if unknown:
        raise ValueError(f"Not editable: {', '.join(sorted(unknown))}")
    async with db.session("alert_rules.update") as s:
        row = await s.scalar(
            update(AlertRuleRow)
            .where(AlertRuleRow.rule_id == rule_id, _ACTIVE_RULE)
            .values(**changes)
            .returning(AlertRuleRow)
        )
        return _rule(row) if row else None


async def _delete_rule_where(condition) -> bool:
    now = _now()
    async with db.session("alert_rules.delete") as s:
        deleted = await s.scalar(
            update(AlertRuleRow).where(condition, _ACTIVE_RULE).values(deleted_at=now).returning(AlertRuleRow.rule_id)
        )
        if deleted is None:
            return False
        await s.execute(
            update(AlertChannelRow)
            .where(AlertChannelRow.rule_id == deleted, _ACTIVE_CHANNEL)
            .values(deleted_at=now)
        )
    return True


async def delete_rule(server_id: str, rule_id: UUID) -> bool:
    """Delete a rule set on this server and the channels that only served it."""
    return await _delete_rule_where(and_(
        AlertRuleRow.rule_id == rule_id, AlertRuleRow.scope == SCOPE_SERVER, AlertRuleRow.server_id == server_id,
    ))


async def delete_rule_by_id(rule_id: UUID) -> bool:
    """Delete a rule wherever it is set, and the channels that only served it."""
    return await _delete_rule_where(AlertRuleRow.rule_id == rule_id)


# ── Channels ──────────────────────────────────────────────────────────────────

async def list_channels(server_id: str) -> list[AlertChannel]:
    """The channels set on this server itself."""
    return await channels_at(Place(SCOPE_SERVER, server_id=server_id))


async def channels_at(place: Place) -> list[AlertChannel]:
    async with db.session() as s:
        rows = await s.scalars(
            select(AlertChannelRow)
            .where(_at_place(AlertChannelRow, place), _ACTIVE_CHANNEL)
            .order_by(AlertChannelRow.rule_id.nulls_first(), AlertChannelRow.created_at)
        )
        return [_channel(r) for r in rows]


_LOOK_UP = object()


async def channels_reaching(server_id: str, group_id: int | None | object = _LOOK_UP) -> list[AlertChannel]:
    """Every channel an alert of this server may go to: global, its group's and its own.
    The evaluator passes the group it already knows; otherwise it is read."""
    if group_id is _LOOK_UP:
        group_id = await group_of(server_id)
    async with db.session() as s:
        rows = await s.scalars(
            select(AlertChannelRow)
            .where(_covering(AlertChannelRow, server_id, group_id), _ACTIVE_CHANNEL)
            .order_by(AlertChannelRow.rule_id.nulls_first(), AlertChannelRow.created_at)
        )
        return [_channel(r) for r in rows]


async def get_channel(server_id: str, channel_id: UUID) -> AlertChannel | None:
    """A channel set on this server itself."""
    channel = await get_channel_by_id(channel_id)
    if channel is None or channel.scope != SCOPE_SERVER or channel.server_id != server_id:
        return None
    return channel


async def get_channel_by_id(channel_id: UUID) -> AlertChannel | None:
    async with db.session() as s:
        row = await s.scalar(select(AlertChannelRow).where(AlertChannelRow.channel_id == channel_id, _ACTIVE_CHANNEL))
        return _channel(row) if row else None


async def channels_for_alert(server_id: str, rule_id: UUID, group_id: int | None = None) -> list[AlertChannel]:
    """Channels whose place covers the server and that take every rule or this one."""
    async with db.session() as s:
        rows = await s.scalars(
            select(AlertChannelRow)
            .where(
                _covering(AlertChannelRow, server_id, group_id),
                or_(AlertChannelRow.rule_id == rule_id, AlertChannelRow.rule_id.is_(None)),
                _ACTIVE_CHANNEL,
            )
            .order_by(AlertChannelRow.created_at)
        )
        return [_channel(r) for r in rows]


async def create_channel(channel: AlertChannel) -> AlertChannel:
    try:
        async with db.session() as s:
            await _check_group(s, channel.group_id)
            await s.execute(insert(AlertChannelRow).values(
                channel_id=channel.channel_id, scope=channel.scope, server_id=channel.server_id,
                group_id=channel.group_id, rule_id=channel.rule_id, channel_type=channel.channel_type,
                config=channel.config, created_at=channel.created_at,
            ))
    except IntegrityError as exc:
        raise _integrity(exc) from None
    return channel


async def move_channel(channel_id: UUID, place: Place) -> AlertChannel | None:
    """Set a channel's place; its type, config and rule stay. None when there is no such channel."""
    try:
        async with db.session("alert_channels.move") as s:
            await _check_group(s, place.group_id)
            row = await s.scalar(
                update(AlertChannelRow)
                .where(AlertChannelRow.channel_id == channel_id, _ACTIVE_CHANNEL)
                .values(scope=place.scope, server_id=place.server_id, group_id=place.group_id)
                .returning(AlertChannelRow)
            )
            return _channel(row) if row else None
    except IntegrityError as exc:
        raise _integrity(exc) from None


async def _delete_channel_where(condition) -> bool:
    async with db.session("alert_channels.delete") as s:
        deleted = await s.scalar(
            update(AlertChannelRow)
            .where(condition, _ACTIVE_CHANNEL)
            .values(deleted_at=_now())
            .returning(AlertChannelRow.channel_id)
        )
    return deleted is not None


async def delete_channel(server_id: str, channel_id: UUID) -> bool:
    """Delete a channel set on this server itself."""
    return await _delete_channel_where(and_(
        AlertChannelRow.channel_id == channel_id,
        AlertChannelRow.scope == SCOPE_SERVER,
        AlertChannelRow.server_id == server_id,
    ))


async def delete_channel_by_id(channel_id: UUID) -> bool:
    return await _delete_channel_where(AlertChannelRow.channel_id == channel_id)


# ── State ─────────────────────────────────────────────────────────────────────

async def rules_to_evaluate(server_ids: list[str]) -> list[RuleToEvaluate]:
    """Every rule that applies on these servers, with where it stands on each."""
    if not server_ids:
        return []
    groups = await _groups_of(server_ids)
    candidates = await _rules_covering(server_ids, {g for g in groups.values() if g is not None})
    pairs = [
        (rule, server_id, group_id)
        for server_id, group_id in groups.items()
        for rule in rule_scope.effective(candidates, server_id, group_id)
    ]
    if not pairs:
        return []
    async with db.session() as s:
        rows = await s.scalars(
            select(AlertStateRow).where(
                AlertStateRow.rule_id.in_({rule.rule_id for rule, _server, _group in pairs}),
                AlertStateRow.server_id.in_(server_ids),
            )
        )
        states = {(row.rule_id, row.server_id): row for row in rows}
    return [
        RuleToEvaluate(rule, server_id, group_id, _state(states.get((rule.rule_id, server_id))))
        for rule, server_id, group_id in pairs
    ]


async def change_state(
    rule_id: UUID, server_id: str, read: AlertState, new: AlertState, event_id: UUID, at: datetime | None = None,
) -> int | None:
    """Apply a change only if the state is still the one `read` saw (compare and set).

    Returns the new version, or None when another evaluator changed it first: the caller
    must not notify. Opening or closing an alert drops its acknowledgement, which belongs
    to one open alert; FIRING and NO_DATA are both open, so going between them keeps it.
    """
    values = {
        "state": new.state,
        "last_fired_at": new.last_fired_at,
        "last_resolved_at": new.last_resolved_at,
        "last_event_id": event_id,
        "changed_at": at or _now(),
    }
    if read.is_open != new.is_open:
        values |= {"acknowledged_at": None, "acknowledged_by": None}
    async with db.session() as s:
        if read.version is None:
            return await s.scalar(
                insert(AlertStateRow)
                .values(rule_id=rule_id, server_id=server_id, version=1, **values)
                .on_conflict_do_nothing(index_elements=["rule_id", "server_id"])
                .returning(AlertStateRow.version)
            )
        return await _compare_and_set(s, rule_id, server_id, read.version, values)


async def _compare_and_set(s, rule_id: UUID, server_id: str, version: int, values: dict) -> int | None:
    return await s.scalar(
        update(AlertStateRow)
        .where(
            AlertStateRow.rule_id == rule_id,
            AlertStateRow.server_id == server_id,
            AlertStateRow.version == version,
        )
        .values(version=AlertStateRow.version + 1, **values)
        .returning(AlertStateRow.version)
    )


async def mark_notified(rule_id: UUID, server_id: str, version: int, notified_state: str, at: datetime) -> int | None:
    """Record what the channels are about to hear, before it is sent (compare and set).

    None: another evaluator got there first, and this one must not send.
    """
    async with db.session() as s:
        return await _compare_and_set(
            s, rule_id, server_id, version, {"notified_state": notified_state, "last_notified_at": at},
        )


class NotOpen(Exception):
    """There is no open alert of this rule on this server."""


class AlreadyAcknowledged(Exception):
    """Someone acknowledged this alert already."""


async def acknowledge(rule_id: UUID, server_id: str, user_id: int, at: datetime | None = None) -> AlertState:
    """Mark an open alert as seen: it stays open and stops repeating.

    Not versioned: the evaluator never writes these columns except to drop them when
    the alert opens or closes, so it cannot undo an acknowledgement it did not see.
    """
    async with db.session() as s:
        row = await s.scalar(
            update(AlertStateRow)
            .where(
                AlertStateRow.rule_id == rule_id, AlertStateRow.server_id == server_id,
                AlertStateRow.state.in_(OPEN_STATES), AlertStateRow.acknowledged_at.is_(None),
            )
            .values(acknowledged_at=at or _now(), acknowledged_by=user_id)
            .returning(AlertStateRow)
        )
        if row is not None:
            return _state(row)
        current = await s.scalar(
            select(AlertStateRow).where(AlertStateRow.rule_id == rule_id, AlertStateRow.server_id == server_id)
        )
    if current is not None and current.state in OPEN_STATES:
        raise AlreadyAcknowledged()
    raise NotOpen()


@dataclass
class OpenAlert:
    rule: AlertRule
    server_id: str
    state: AlertState
    acknowledged_by_name: str | None


async def open_alerts(server_id: str | None = None) -> list[OpenAlert]:
    """Alerts firing or without data now, oldest first, with who acknowledged them."""
    query = (
        select(AlertStateRow, AlertRuleRow, User.username)
        .join(AlertRuleRow, AlertRuleRow.rule_id == AlertStateRow.rule_id)
        .outerjoin(User, User.id == AlertStateRow.acknowledged_by)
        .where(AlertStateRow.state.in_(OPEN_STATES), _ACTIVE_RULE, AlertRuleRow.enabled)
        .order_by(AlertStateRow.changed_at.nulls_first(), AlertStateRow.server_id, AlertRuleRow.metric_name)
    )
    if server_id is not None:
        query = query.where(AlertStateRow.server_id == server_id)
    async with db.session() as s:
        rows = await s.execute(query)
        return [OpenAlert(_rule(rule), state.server_id, _state(state), username) for state, rule, username in rows]


async def firing_severities(server_id: str) -> dict[str, str]:
    """{rule_id: severity} of the rules firing on this server now.

    Only rules still judged there count: one overridden or switched off on the server keeps
    its last state row, which must not keep the server looking alarmed.
    """
    judged = {rule.rule_id for rule in await effective_rules(server_id)}
    if not judged:
        return {}
    async with db.session() as s:
        rows = await s.execute(
            select(AlertRuleRow.rule_id, AlertRuleRow.severity)
            .join(AlertStateRow, AlertStateRow.rule_id == AlertRuleRow.rule_id)
            .where(
                AlertStateRow.server_id == server_id, AlertStateRow.state == STATE_FIRING,
                AlertRuleRow.rule_id.in_(judged),
            )
        )
        return {str(rule_id): severity for rule_id, severity in rows}


# ── Default rules ─────────────────────────────────────────────────────────────

def _same_values(a: AlertRule):
    return and_(
        AlertRuleRow.metric_name == a.metric_name, AlertRuleRow.operator == a.operator,
        AlertRuleRow.threshold == a.threshold, AlertRuleRow.severity == a.severity,
        AlertRuleRow.cooldown_minutes == a.cooldown_minutes, AlertRuleRow.alert_mode == a.alert_mode,
    )


async def adopt_global_defaults(rules: list[AlertRule]) -> bool:
    """Store the default rules once, as global ones. True if they were stored now.

    Nothing happens when any global rule exists or ever existed, so deleting one does
    not bring it back. Per-server copies of a default (0.2.0 gave each server its own)
    are removed in the same transaction: each one's state and rule-bound channels move
    to the global rule, so an alert firing now does not fire again. A server that had
    the defaults and deleted one gets a switched-off rule in its place, so it stays off.
    """
    async with db.session("alert_rules.adopt_defaults") as s:
        # Two workers must not both adopt; the evaluator's lock already makes this rare.
        await s.execute(text("SELECT pg_advisory_xact_lock(hashtext('maestro.adopt_global_defaults'))"))
        if await s.scalar(select(exists().where(AlertRuleRow.scope == SCOPE_GLOBAL))):
            return False
        had_defaults = set(await s.scalars(select(AlertDefaultsApplied.server_id)))
        now = _now()
        for rule in rules:
            await s.execute(insert(AlertRuleRow).values(**_rule_values(rule)))
            copies = list(await s.scalars(
                select(AlertRuleRow).where(AlertRuleRow.scope == SCOPE_SERVER, _ACTIVE_RULE, _same_values(rule))
            ))
            for copy in copies:
                await s.execute(
                    text(
                        "INSERT INTO alert_state"
                        " (rule_id, server_id, state, last_fired_at, last_resolved_at, last_event_id, version)"
                        " SELECT :global_id, server_id, state, last_fired_at, last_resolved_at, last_event_id, version"
                        " FROM alert_state WHERE rule_id = :copy_id"
                    ),
                    {"global_id": rule.rule_id, "copy_id": copy.rule_id},
                )
                await s.execute(
                    update(AlertChannelRow)
                    .where(AlertChannelRow.rule_id == copy.rule_id, _ACTIVE_CHANNEL)
                    .values(rule_id=rule.rule_id)
                )
                await s.execute(update(AlertRuleRow).where(AlertRuleRow.rule_id == copy.rule_id).values(deleted_at=now))
            with_own_rule = set(await s.scalars(
                select(AlertRuleRow.server_id).where(
                    AlertRuleRow.scope == SCOPE_SERVER, _ACTIVE_RULE,
                    AlertRuleRow.metric_name == rule.metric_name, AlertRuleRow.severity == rule.severity,
                )
            ))
            adopted = {copy.server_id for copy in copies}
            for server_id in sorted(had_defaults - with_own_rule - adopted):
                switched_off = replace(
                    rule, rule_id=uuid4(), scope=SCOPE_SERVER, server_id=server_id, enabled=False,
                )
                await s.execute(insert(AlertRuleRow).values(**_rule_values(switched_off)))
    return True
