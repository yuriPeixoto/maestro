"""Alert rules, channels and state (moved from ClickHouse and Redis).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOT_DELETED = sa.text("deleted_at IS NULL")
_TOUCHED_TABLES = ("alert_rules", "alert_channels", "alert_state")


def _timestamp(name: str, nullable: bool = False) -> sa.Column:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("rule_id", sa.Uuid(), primary_key=True),
        sa.Column("server_id", sa.Text(), nullable=False),
        sa.Column("metric_name", sa.Text(), nullable=False),
        sa.Column("operator", sa.Text(), nullable=False),
        sa.Column("threshold", sa.Double(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False),
        sa.Column("alert_mode", sa.Text(), server_default="static", nullable=False),
        sa.Column("ml_score_threshold", sa.Double(), server_default="0.7", nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _timestamp("deleted_at", nullable=True),
        sa.CheckConstraint("operator IN ('>', '<', '>=', '<=', '==')", name="alert_rules_operator_check"),
        sa.CheckConstraint("severity IN ('warning', 'critical')", name="alert_rules_severity_check"),
        sa.CheckConstraint("alert_mode IN ('static', 'ml', 'both')", name="alert_rules_alert_mode_check"),
        sa.CheckConstraint("cooldown_minutes >= 0", name="alert_rules_cooldown_check"),
        sa.CheckConstraint("ml_score_threshold BETWEEN 0 AND 1", name="alert_rules_ml_score_check"),
        sa.UniqueConstraint("rule_id", "server_id", name="alert_rules_rule_server_key"),
    )
    op.create_index(
        "alert_rules_active_unique", "alert_rules",
        ["server_id", "metric_name", "operator", "threshold", "severity"],
        unique=True, postgresql_where=_NOT_DELETED,
    )

    op.create_table(
        "alert_channels",
        sa.Column("channel_id", sa.Uuid(), primary_key=True),
        sa.Column("server_id", sa.Text(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=True),
        sa.Column("channel_type", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _timestamp("deleted_at", nullable=True),
        sa.ForeignKeyConstraint(
            ["rule_id", "server_id"], ["alert_rules.rule_id", "alert_rules.server_id"],
            name="alert_channels_rule_fkey", ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "channel_type IN ('webhook', 'email', 'slack', 'telegram')", name="alert_channels_type_check",
        ),
        sa.CheckConstraint("jsonb_typeof(config) = 'object'", name="alert_channels_config_check"),
    )
    op.create_index("alert_channels_server_active", "alert_channels", ["server_id"], postgresql_where=_NOT_DELETED)
    op.create_index("alert_channels_rule_active", "alert_channels", ["rule_id"], postgresql_where=_NOT_DELETED)

    op.create_table(
        "alert_state",
        sa.Column(
            "rule_id", sa.Uuid(), sa.ForeignKey("alert_rules.rule_id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("state", sa.Text(), server_default="INACTIVE", nullable=False),
        _timestamp("last_fired_at", nullable=True),
        _timestamp("last_resolved_at", nullable=True),
        sa.Column("last_event_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.BigInteger(), server_default="0", nullable=False),
        _timestamp("updated_at"),
        sa.CheckConstraint("state IN ('INACTIVE', 'FIRING', 'RESOLVED')", name="alert_state_state_check"),
    )
    op.create_index("alert_state_firing", "alert_state", ["rule_id"], postgresql_where=sa.text("state = 'FIRING'"))

    op.create_table(
        "alert_defaults_applied",
        sa.Column("server_id", sa.Text(), primary_key=True),
        _timestamp("applied_at"),
    )

    # updated_at follows every change, including one made by hand in a SQL client.
    op.execute(
        """
        CREATE FUNCTION maestro_touch_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$
        """
    )
    for table in _TOUCHED_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_touch_updated_at BEFORE UPDATE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION maestro_touch_updated_at()"
        )


def downgrade() -> None:
    for table in _TOUCHED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_touch_updated_at ON {table}")
    op.execute("DROP FUNCTION IF EXISTS maestro_touch_updated_at()")
    op.drop_table("alert_defaults_applied")
    op.drop_index("alert_state_firing", table_name="alert_state")
    op.drop_table("alert_state")
    op.drop_index("alert_channels_rule_active", table_name="alert_channels")
    op.drop_index("alert_channels_server_active", table_name="alert_channels")
    op.drop_table("alert_channels")
    op.drop_index("alert_rules_active_unique", table_name="alert_rules")
    op.drop_table("alert_rules")
