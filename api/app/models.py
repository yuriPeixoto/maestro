"""Postgres tables. Any change here needs an Alembic migration (api/alembic/versions)."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
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


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    token: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, server_default="false")


class AlertRuleRow(Base):
    """A threshold or ML rule of one server. Deleting sets deleted_at: the alert history
    in ClickHouse still names the rule, and a re-run of the import does not bring it back."""

    __tablename__ = "alert_rules"

    rule_id: Mapped[UUID] = mapped_column(primary_key=True)
    server_id: Mapped[str] = mapped_column(Text)
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
        # Target of the channels' (rule_id, server_id) key: a channel cannot take another server's rule.
        UniqueConstraint("rule_id", "server_id", name="alert_rules_rule_server_key"),
        # The same rule twice on one server would fire twice.
        Index(
            "alert_rules_active_unique",
            "server_id", "metric_name", "operator", "threshold", "severity",
            unique=True, postgresql_where=_NOT_DELETED,
        ),
    )


class AlertChannelRow(Base):
    """Where a server's alerts go. rule_id NULL: every rule of the server."""

    __tablename__ = "alert_channels"

    channel_id: Mapped[UUID] = mapped_column(primary_key=True)
    server_id: Mapped[str] = mapped_column(Text)
    rule_id: Mapped[UUID | None] = mapped_column()
    channel_type: Mapped[str] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["rule_id", "server_id"], ["alert_rules.rule_id", "alert_rules.server_id"],
            name="alert_channels_rule_fkey", ondelete="CASCADE",
        ),
        CheckConstraint(
            "channel_type IN ('webhook', 'email', 'slack', 'telegram')", name="alert_channels_type_check",
        ),
        CheckConstraint("jsonb_typeof(config) = 'object'", name="alert_channels_config_check"),
        Index("alert_channels_server_active", "server_id", postgresql_where=_NOT_DELETED),
        Index("alert_channels_rule_active", "rule_id", postgresql_where=_NOT_DELETED),
    )


class AlertStateRow(Base):
    """Where each rule stands. `version` grows on every change, and a change only applies
    when the version read is still current, so two evaluators cannot both fire one alert.
    `last_event_id` is the event of the last change: with the channel it keys a delivery."""

    __tablename__ = "alert_state"

    rule_id: Mapped[UUID] = mapped_column(ForeignKey("alert_rules.rule_id", ondelete="CASCADE"), primary_key=True)
    state: Mapped[str] = mapped_column(Text, server_default="INACTIVE")
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_id: Mapped[UUID | None] = mapped_column()
    version: Mapped[int] = mapped_column(BigInteger, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("state IN ('INACTIVE', 'FIRING', 'RESOLVED')", name="alert_state_state_check"),
        Index("alert_state_firing", "rule_id", postgresql_where=text("state = 'FIRING'")),
    )


class AlertDefaultsApplied(Base):
    """Servers that already got the default rules; rules deleted afterwards stay deleted."""

    __tablename__ = "alert_defaults_applied"

    server_id: Mapped[str] = mapped_column(Text, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
