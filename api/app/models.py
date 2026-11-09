"""Postgres tables. Any change here needs an Alembic migration (api/alembic/versions)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    Time,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, INTERVAL, JSONB, TSTZRANGE, ExcludeConstraint, Range

DateTimeRange = Range[datetime]
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

_NOT_DELETED = text("deleted_at IS NULL")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    username: Mapped[str] = mapped_column(Text, unique=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # The password was chosen by someone else: the account can only change it until it does.
    must_change_password: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # NULL: the account has seen no release notes yet.
    last_seen_version: Mapped[str | None] = mapped_column(Text)
    # Login lockout: failures inside the window, and until when the account is locked.
    failed_login_count: Mapped[int] = mapped_column(Integer, server_default="0")
    last_failed_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    full_name: Mapped[str | None] = mapped_column(Text)
    # One of app.permissions.Role.
    role: Mapped[str] = mapped_column(Text, server_default="viewer")
    # Set: the account cannot log in, and its sessions are refused. Accounts are never deleted.
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last authenticated request, written at most every few minutes (app.auth_db.LAST_SEEN_RESOLUTION).
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Tokens issued before this moment are refused (temporary password, deactivation).
    sessions_valid_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("role IN ('viewer', 'operator', 'admin')", name="users_role_check"),
    )


class AuditLogRow(Base):
    """Who did what, when, to what and from where. Row changes on the audited tables are
    written by the maestro_audit_row() trigger (so edits made straight in the database are
    caught too); events that change no row (login, logout, a channel test) by app.audit.
    Append-only: a trigger refuses UPDATE and DELETE, and an account with entries cannot be deleted."""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    # The account's username, or "<database user> via <application_name>" outside the API.
    actor: Mapped[str] = mapped_column(Text)
    source_ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    target_table: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint("action <> ''", name="audit_log_action_check"),
        Index("ix_audit_log_occurred_at", text("occurred_at DESC")),
        Index("ix_audit_log_actor_user_id", "actor_user_id", text("id DESC")),
        Index("ix_audit_log_action", "action", text("id DESC")),
    )


_SCOPE_CHECK = (
    "(scope = 'global' AND server_id IS NULL AND group_id IS NULL)"
    " OR (scope = 'group' AND server_id IS NULL AND group_id IS NOT NULL)"
    " OR (scope = 'server' AND server_id IS NOT NULL AND group_id IS NULL)"
)


class ServerGroupRow(Base):
    """A named set of servers (web, robots, database). A server is in at most one group."""

    __tablename__ = "server_groups"

    group_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("btrim(name) <> ''", name="server_groups_name_check"),
        Index("server_groups_name_unique", text("lower(name)"), unique=True, postgresql_where=_NOT_DELETED),
    )


class ServerRow(Base):
    """A server Maestro has seen. `server_id` is the hostname the agent reports: the identity
    in notifications, the audit log and searches. `label` is a shared name everyone sees."""

    __tablename__ = "servers"

    server_id: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str | None] = mapped_column(Text)
    group_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("server_groups.group_id"))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("label IS NULL OR btrim(label) <> ''", name="servers_label_check"),
        Index("servers_label_unique", text("lower(label)"), unique=True, postgresql_where=text("label IS NOT NULL")),
        Index("servers_group", "group_id"),
    )


class ServerNicknameRow(Base):
    """A name one account gives a server for its own screens. Personal preference, not
    configuration: any role may set its own, nobody else sees it, and it is not audited."""

    __tablename__ = "server_nicknames"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    server_id: Mapped[str] = mapped_column(
        Text, ForeignKey("servers.server_id", ondelete="CASCADE"), primary_key=True,
    )
    nickname: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("btrim(nickname) <> '' AND length(nickname) <= 60", name="server_nicknames_nickname_check"),
        # Two servers with the same name on one person's screen could not be told apart.
        Index("server_nicknames_user_nickname_unique", "user_id", text("lower(nickname)"), unique=True),
    )


class AlertRuleRow(Base):
    """A threshold or ML rule for every server (global), a group or one server. For each
    metric and severity the most specific rule wins; `enabled` false switches the inherited
    rule off there. Deleting sets deleted_at: the alert history in ClickHouse still names it."""

    __tablename__ = "alert_rules"

    rule_id: Mapped[UUID] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(Text, server_default="server")
    server_id: Mapped[str | None] = mapped_column(Text)
    group_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("server_groups.group_id"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    metric_name: Mapped[str] = mapped_column(Text)
    operator: Mapped[str] = mapped_column(Text)
    threshold: Mapped[float] = mapped_column(Double)
    severity: Mapped[str] = mapped_column(Text)
    cooldown_minutes: Mapped[int] = mapped_column(Integer)
    alert_mode: Mapped[str] = mapped_column(Text, server_default="static")
    ml_score_threshold: Mapped[float] = mapped_column(Double, server_default="0.7")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("operator IN ('>', '<', '>=', '<=', '==')", name="alert_rules_operator_check"),
        CheckConstraint("severity IN ('warning', 'critical')", name="alert_rules_severity_check"),
        CheckConstraint("alert_mode IN ('static', 'ml', 'both')", name="alert_rules_alert_mode_check"),
        CheckConstraint("cooldown_minutes >= 0", name="alert_rules_cooldown_check"),
        CheckConstraint("ml_score_threshold BETWEEN 0 AND 1", name="alert_rules_ml_score_check"),
        CheckConstraint(_SCOPE_CHECK, name="alert_rules_scope_check"),
        # One rule per metric and severity at each place: a second one would leave nothing to say which wins.
        Index(
            "alert_rules_active_unique",
            "scope", text("coalesce(server_id, '')"), text("coalesce(group_id, 0)"), "metric_name", "severity",
            unique=True, postgresql_where=_NOT_DELETED,
        ),
        Index("alert_rules_group_active", "group_id", postgresql_where=_NOT_DELETED),
    )


class AlertChannelRow(Base):
    """Where alerts go: every server (global), a group's or one server's. rule_id NULL: every
    rule. Channels add up: an alert goes to each channel whose place covers its server."""

    __tablename__ = "alert_channels"

    channel_id: Mapped[UUID] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(Text, server_default="server")
    server_id: Mapped[str | None] = mapped_column(Text)
    group_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("server_groups.group_id"))
    rule_id: Mapped[UUID | None] = mapped_column(ForeignKey("alert_rules.rule_id", ondelete="CASCADE"))
    channel_type: Mapped[str] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "channel_type IN ('webhook', 'email', 'slack', 'telegram')", name="alert_channels_type_check",
        ),
        CheckConstraint("jsonb_typeof(config) = 'object'", name="alert_channels_config_check"),
        CheckConstraint(_SCOPE_CHECK, name="alert_channels_scope_check"),
        Index("alert_channels_server_active", "server_id", postgresql_where=_NOT_DELETED),
        Index("alert_channels_group_active", "group_id", postgresql_where=_NOT_DELETED),
        Index("alert_channels_rule_active", "rule_id", postgresql_where=_NOT_DELETED),
    )


class AlertStateRow(Base):
    """Where each rule stands on each server (a global rule has one state per server).
    `version` grows on every change, and a change only applies when the version read is
    still current, so two evaluators cannot both fire one alert. `last_event_id` is the
    event of the last change: with the channel it keys a delivery."""

    __tablename__ = "alert_state"

    rule_id: Mapped[UUID] = mapped_column(ForeignKey("alert_rules.rule_id", ondelete="CASCADE"), primary_key=True)
    server_id: Mapped[str] = mapped_column(Text, primary_key=True)
    state: Mapped[str] = mapped_column(Text, server_default="INACTIVE")
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_id: Mapped[UUID | None] = mapped_column()
    version: Mapped[int] = mapped_column(BigInteger, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("state IN ('INACTIVE', 'FIRING', 'RESOLVED')", name="alert_state_state_check"),
        Index("alert_state_firing", "server_id", postgresql_where=text("state = 'FIRING'")),
    )


class AlertDefaultsApplied(Base):
    """Servers that got per-server default rules before 0.3.0. Read only when those rules
    are turned into global ones (app.default_rules); kept as the way back until 0.4.0."""

    __tablename__ = "alert_defaults_applied"

    server_id: Mapped[str] = mapped_column(Text, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlertSilenceRow(Base):
    """Quiet on purpose, with a deadline, a reason and an author: rules keep being judged
    and events recorded, but no notification goes out. rule_id NULL: every rule.
    Ending one early moves the end of `during` to now."""

    __tablename__ = "alert_silences"

    silence_id: Mapped[UUID] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(Text)
    server_id: Mapped[str | None] = mapped_column(Text)
    group_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("server_groups.group_id"))
    rule_id: Mapped[UUID | None] = mapped_column(ForeignKey("alert_rules.rule_id", ondelete="CASCADE"))
    during: Mapped[DateTimeRange] = mapped_column(TSTZRANGE)
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    ended_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(_SCOPE_CHECK, name="alert_silences_scope_check"),
        CheckConstraint("btrim(reason) <> ''", name="alert_silences_reason_check"),
        # A silence always has a deadline.
        CheckConstraint(
            "NOT isempty(during) AND NOT lower_inf(during) AND NOT upper_inf(during)",
            name="alert_silences_during_check",
        ),
        Index("alert_silences_ends", text("upper(during)")),
    )


class MaintenanceWindowRow(Base):
    """Planned work on one server: once (`during`) or every week (`weekdays`, `local_start`,
    `duration` in `time_zone`, until `repeat_until`). Alerts are judged but not sent while it
    lasts. Its dates live in maintenance_occurrences, where the database refuses overlaps."""

    __tablename__ = "maintenance_windows"

    window_id: Mapped[UUID] = mapped_column(primary_key=True)
    server_id: Mapped[str] = mapped_column(Text, ForeignKey("servers.server_id"))
    reason: Mapped[str] = mapped_column(Text)
    during: Mapped[DateTimeRange | None] = mapped_column(TSTZRANGE)
    weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))  # ISO: 1 Monday … 7 Sunday
    local_start: Mapped[time | None] = mapped_column(Time)
    duration: Mapped[timedelta | None] = mapped_column(INTERVAL)
    time_zone: Mapped[str | None] = mapped_column(Text)
    repeat_until: Mapped[date | None] = mapped_column(Date)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("btrim(reason) <> ''", name="maintenance_windows_reason_check"),
        CheckConstraint(
            "(during IS NOT NULL AND weekdays IS NULL AND local_start IS NULL AND duration IS NULL"
            " AND time_zone IS NULL AND repeat_until IS NULL"
            " AND NOT isempty(during) AND NOT lower_inf(during) AND NOT upper_inf(during))"
            " OR (during IS NULL AND weekdays IS NOT NULL AND cardinality(weekdays) > 0"
            " AND weekdays <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]"
            " AND local_start IS NOT NULL AND time_zone IS NOT NULL"
            " AND duration > interval '0' AND duration <= interval '24 hours')",
            name="maintenance_windows_shape_check",
        ),
        Index("maintenance_windows_server_active", "server_id", postgresql_where=_NOT_DELETED),
    )


class MaintenanceOccurrenceRow(Base):
    """Each time a window happens. The exclusion constraint (btree_gist) refuses two
    occurrences of one server that overlap, and "in maintenance now" is `during @> now()`.
    A weekly window gets its next weeks written ahead (app.maintenance)."""

    __tablename__ = "maintenance_occurrences"

    occurrence_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    window_id: Mapped[UUID] = mapped_column(ForeignKey("maintenance_windows.window_id", ondelete="CASCADE"))
    server_id: Mapped[str] = mapped_column(Text)
    during: Mapped[DateTimeRange] = mapped_column(TSTZRANGE)

    __table_args__ = (
        CheckConstraint(
            "NOT isempty(during) AND NOT lower_inf(during) AND NOT upper_inf(during)",
            name="maintenance_occurrences_during_check",
        ),
        ExcludeConstraint(
            ("server_id", "="), ("during", "&&"), name="maintenance_occurrences_no_overlap", using="gist",
        ),
        Index("maintenance_occurrences_window", "window_id", text("lower(during)")),
    )
