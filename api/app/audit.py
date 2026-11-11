"""The audit log: who did what, when, to what and from where.

Row changes on users, alert_rules and alert_channels are written by the database
(trigger maestro_audit_row, Alembic 0003), which reads the actor from settings that
app.db.session() sets for the transaction (SET LOCAL). Without them, as in a change
made straight in the database, the trigger records the database user and the
application_name. `record()` writes the events that change no row.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import insert, select

from app import db
from app.models import (
    AlertChannelRow,
    AlertRuleRow,
    AlertSilenceRow,
    AuditLogRow,
    MaintenanceWindowRow,
    ServerGroupRow,
    ServerRow,
    User,
)

_LOGIN_ACTIONS = "auth."


@dataclass(frozen=True)
class Actor:
    user_id: int | None
    name: str
    ip: str | None = None
    user_agent: str | None = None


# Set for the current request by app.auth once the caller is known (or by the login route).
current_actor: ContextVar[Actor | None] = ContextVar("maestro_audit_actor", default=None)

# What the worker signs its own changes with (adopting the default rules, registering
# servers). The trigger takes the actor only from the API's database user, which the
# worker shares, so another login naming itself "maestro-worker" is still logged as
# "<database user> via <program>", outside Maestro (ADR-012).
WORKER_ACTOR = Actor(user_id=None, name="maestro-worker")


def set_actor(actor: Actor) -> None:
    current_actor.set(actor)


def session_settings(action: str | None) -> dict[str, str]:
    """What the trigger reads for this transaction; empty outside a request."""
    actor = current_actor.get()
    values: dict[str, str] = {}
    if actor is not None:
        values = {
            "maestro.actor": actor.name,
            "maestro.actor_id": "" if actor.user_id is None else str(actor.user_id),
            "maestro.ip": actor.ip or "",
            "maestro.user_agent": actor.user_agent or "",
        }
    if action:
        values["maestro.action"] = action
    return values


async def record(
    action: str,
    *,
    target_table: str | None = None,
    target_id: str | int | None = None,
    details: dict | None = None,
    actor: Actor | None = None,
) -> None:
    """An event that changes no audited row (login, logout, a channel test)."""
    who = actor or current_actor.get()
    async with db.session() as s:
        await s.execute(insert(AuditLogRow).values(
            actor_user_id=who.user_id if who else None,
            actor=who.name if who else "anonymous",
            source_ip=who.ip if who else None,
            user_agent=who.user_agent if who else None,
            action=action,
            target_table=target_table,
            target_id=None if target_id is None else str(target_id),
            after=details,
        ))


def _as_dict(row: AuditLogRow) -> dict:
    return {
        "id": row.id,
        "occurred_at": row.occurred_at.astimezone(timezone.utc).isoformat(),
        "actor_user_id": row.actor_user_id,
        "actor": row.actor,
        "source_ip": None if row.source_ip is None else str(row.source_ip),
        "user_agent": row.user_agent,
        "action": row.action,
        "target_table": row.target_table,
        "target_id": row.target_id,
        "before": row.before,
        "after": row.after,
    }


async def describe_targets(entries: list[dict]) -> dict[tuple[str, str], dict]:
    """What each entry's target is, for the screen: an account's name, a rule's metric and
    limit, a channel's type, keyed by (target_table, target_id). Soft-deleted rules and
    channels are still described; an id the table no longer has is left out."""
    wanted: dict[str, set[str]] = {}
    for entry in entries:
        if entry["target_table"] and entry["target_id"]:
            wanted.setdefault(entry["target_table"], set()).add(entry["target_id"])
    found: dict[tuple[str, str], dict] = {}
    async with db.session() as s:
        if user_ids := _ints(wanted.get("users", set())):
            for row in await s.execute(select(User.id, User.username, User.full_name).where(User.id.in_(user_ids))):
                found[("users", str(row.id))] = {
                    "kind": "user", "username": row.username, "full_name": row.full_name,
                }
        if rule_ids := _uuids(wanted.get("alert_rules", set())):
            query = select(AlertRuleRow).where(AlertRuleRow.rule_id.in_(rule_ids))
            for rule in await s.scalars(query):
                found[("alert_rules", str(rule.rule_id))] = {
                    "kind": "rule", "scope": rule.scope, "server_id": rule.server_id, "group_id": rule.group_id,
                    "metric_name": rule.metric_name,
                    "operator": rule.operator, "threshold": rule.threshold, "deleted": rule.deleted_at is not None,
                }
        if channel_ids := _uuids(wanted.get("alert_channels", set())):
            query = select(AlertChannelRow).where(AlertChannelRow.channel_id.in_(channel_ids))
            for channel in await s.scalars(query):
                found[("alert_channels", str(channel.channel_id))] = {
                    "kind": "channel", "scope": channel.scope, "server_id": channel.server_id,
                    "group_id": channel.group_id, "channel_type": channel.channel_type,
                    "deleted": channel.deleted_at is not None,
                }
        await _describe_places(s, wanted, found)
    return found


async def _describe_places(s, wanted: dict[str, set[str]], found: dict[tuple[str, str], dict]) -> None:
    """Servers, groups, silences, maintenance windows and acknowledged alerts (0.3.0)."""
    if server_ids := wanted.get("servers"):
        for row in await s.execute(select(ServerRow.server_id, ServerRow.label).where(ServerRow.server_id.in_(server_ids))):
            found[("servers", row.server_id)] = {"kind": "server", "server_id": row.server_id, "label": row.label}
    if group_ids := _ints(wanted.get("server_groups", set())):
        for group in await s.scalars(select(ServerGroupRow).where(ServerGroupRow.group_id.in_(group_ids))):
            found[("server_groups", str(group.group_id))] = {
                "kind": "group", "name": group.name, "deleted": group.deleted_at is not None,
            }
    if silence_ids := _uuids(wanted.get("alert_silences", set())):
        for silence in await s.scalars(select(AlertSilenceRow).where(AlertSilenceRow.silence_id.in_(silence_ids))):
            found[("alert_silences", str(silence.silence_id))] = {
                "kind": "silence", "scope": silence.scope, "server_id": silence.server_id,
                "group_id": silence.group_id, "reason": silence.reason,
            }
    if window_ids := _uuids(wanted.get("maintenance_windows", set())):
        for window in await s.scalars(select(MaintenanceWindowRow).where(MaintenanceWindowRow.window_id.in_(window_ids))):
            found[("maintenance_windows", str(window.window_id))] = {
                "kind": "maintenance", "server_id": window.server_id, "reason": window.reason,
                "weekly": window.weekdays is not None, "deleted": window.deleted_at is not None,
            }
    await _describe_acknowledged(s, wanted.get("alert_state", set()), found)


async def _describe_acknowledged(s, keys: set[str], found: dict[tuple[str, str], dict]) -> None:
    """An acknowledgement names "<rule id>:<server id>": the rule and the server."""
    pairs = {}
    for key in keys:
        rule_part, _, server_id = key.partition(":")
        if parsed := _uuids({rule_part}):
            pairs[key] = (parsed[0], server_id)
    if not pairs:
        return
    rules = {
        rule.rule_id: rule
        for rule in await s.scalars(select(AlertRuleRow).where(AlertRuleRow.rule_id.in_({r for r, _ in pairs.values()})))
    }
    for key, (rule_id, server_id) in pairs.items():
        if rule := rules.get(rule_id):
            found[("alert_state", key)] = {
                "kind": "alert", "server_id": server_id, "metric_name": rule.metric_name, "severity": rule.severity,
            }


# Per audited table, what describes the target and is in the row the trigger copied.
_SNAPSHOT_FIELDS: dict[str, tuple[str, ...]] = {
    "users": ("username", "full_name"),
    "alert_rules": ("scope", "server_id", "group_id", "metric_name", "operator", "threshold"),
    "alert_channels": ("scope", "server_id", "group_id", "channel_type"),
    "servers": ("server_id", "label"),
    "server_groups": ("name",),
    "alert_silences": ("scope", "server_id", "group_id", "reason"),
    "maintenance_windows": ("server_id", "reason", "weekdays"),
}


def target_as_it_was(entry: dict, current: dict | None) -> dict | None:
    """The target as the entry's own row had it: after the change, or before a delete.

    A rule created at 1% and later edited to 99% reads 1% on its creation. Whether it
    was removed since still comes from `current`. An event that copied no row (a login,
    a channel test) keeps the description of now.
    """
    if current is None:
        return None
    snapshot = entry["after"] or entry["before"]
    fields = _SNAPSHOT_FIELDS.get(entry["target_table"] or "")
    if not fields or not snapshot or not all(field in snapshot for field in fields):
        return current
    described = {**current, **{field: snapshot[field] for field in fields if field in current}}
    if current["kind"] == "maintenance":
        described["weekly"] = snapshot["weekdays"] is not None
    return described


def _ints(values: set[str]) -> list[int]:
    return [int(value) for value in values if value.isdigit()]


def _uuids(values: set[str]) -> list[UUID]:
    parsed = []
    for value in values:
        try:
            parsed.append(UUID(value))
        except ValueError:
            continue  # not an id this table could hold
    return parsed


async def list_entries(
    *,
    actor_user_id: int | None = None,
    outside: bool = False,
    by_worker: bool = False,
    action: str | None = None,
    target_table: str | None = None,
    target_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    before_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """Newest first. `action` matches exactly, or a prefix when it ends with a dot
    ("users." is every change to an account). `outside` keeps the changes no account
    made: straight in the database, or by a process with no caller; `by_worker` keeps
    what Maestro's worker did on its own. `before_id` continues a page."""
    criteria = []
    if actor_user_id is not None:
        criteria.append(AuditLogRow.actor_user_id == actor_user_id)
    if outside:
        criteria.append(AuditLogRow.actor_user_id.is_(None))
        # A refused login has no account behind it either, but it is not a change.
        criteria.append(AuditLogRow.action.not_like(f"{_LOGIN_ACTIONS}%"))
        criteria.append(AuditLogRow.actor != WORKER_ACTOR.name)
    if by_worker:
        criteria.append(AuditLogRow.actor_user_id.is_(None))
        criteria.append(AuditLogRow.actor == WORKER_ACTOR.name)
    if action:
        criteria.append(
            AuditLogRow.action.startswith(action, autoescape=True) if action.endswith(".")
            else AuditLogRow.action == action
        )
    if target_table:
        criteria.append(AuditLogRow.target_table == target_table)
    if target_id:
        criteria.append(AuditLogRow.target_id == target_id)
    if since:
        criteria.append(AuditLogRow.occurred_at >= since)
    if until:
        criteria.append(AuditLogRow.occurred_at < until)
    if before_id is not None:
        criteria.append(AuditLogRow.id < before_id)
    query = select(AuditLogRow).where(*criteria).order_by(AuditLogRow.id.desc()).limit(limit)
    async with db.session() as s:
        return [_as_dict(row) for row in await s.scalars(query)]

