"""Servers, groups and names; rules and channels for every server, a group or one server;
silences and maintenance windows.

Existing rules and channels keep their server (scope 'server'). The alert state gains the
server it is about, because a global rule has one state per server. Turning the default
rules into global ones is data, not schema: the worker does it once (app.default_rules).

Needs the btree_gist extension (trusted since Postgres 13: the database owner may create it).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-09
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOT_DELETED = sa.text("deleted_at IS NULL")
_SCOPE_CHECK = (
    "(scope = 'global' AND server_id IS NULL AND group_id IS NULL)"
    " OR (scope = 'group' AND server_id IS NULL AND group_id IS NOT NULL)"
    " OR (scope = 'server' AND server_id IS NOT NULL AND group_id IS NULL)"
)
_RANGE_IS_BOUNDED = "NOT isempty(during) AND NOT lower_inf(during) AND NOT upper_inf(during)"

_TOUCHED_TABLES = ("server_groups", "servers", "server_nicknames", "alert_silences", "maintenance_windows")
# Same arguments as in 0003: key column, then columns whose change alone is not logged.
_AUDITED = {
    "server_groups": ("group_id", "skip:updated_at"),
    "servers": ("server_id", "skip:updated_at"),
    "alert_silences": ("silence_id", "skip:updated_at"),
    "maintenance_windows": ("window_id", "skip:updated_at"),
}


def _timestamp(name: str, nullable: bool = False) -> sa.Column:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _group_fk() -> sa.Column:
    return sa.Column("group_id", sa.BigInteger(), sa.ForeignKey("server_groups.group_id"), nullable=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "server_groups",
        sa.Column("group_id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _timestamp("deleted_at", nullable=True),
        sa.CheckConstraint("btrim(name) <> ''", name="server_groups_name_check"),
    )
    op.create_index(
        "server_groups_name_unique", "server_groups", [sa.text("lower(name)")],
        unique=True, postgresql_where=_NOT_DELETED,
    )

    op.create_table(
        "servers",
        sa.Column("server_id", sa.Text(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=True),
        _group_fk(),
        _timestamp("first_seen_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint("label IS NULL OR btrim(label) <> ''", name="servers_label_check"),
    )
    op.create_index(
        "servers_label_unique", "servers", [sa.text("lower(label)")],
        unique=True, postgresql_where=sa.text("label IS NOT NULL"),
    )
    op.create_index("servers_group", "servers", ["group_id"])
    # Every server some rule or channel already names; the worker adds the others from the heartbeats.
    op.execute(
        "INSERT INTO servers (server_id)"
        " SELECT server_id FROM alert_rules UNION SELECT server_id FROM alert_channels"
        " UNION SELECT server_id FROM alert_defaults_applied"
        " ON CONFLICT DO NOTHING"
    )

    op.create_table(
        "server_nicknames",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "server_id", sa.Text(), sa.ForeignKey("servers.server_id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("nickname", sa.Text(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "btrim(nickname) <> '' AND length(nickname) <= 60", name="server_nicknames_nickname_check",
        ),
    )
    op.create_index(
        "server_nicknames_user_nickname_unique", "server_nicknames", ["user_id", sa.text("lower(nickname)")],
        unique=True,
    )

    # Rules: a place (scope) instead of always a server.
    op.drop_constraint("alert_channels_rule_fkey", "alert_channels", type_="foreignkey")
    op.drop_constraint("alert_rules_rule_server_key", "alert_rules", type_="unique")
    op.drop_index("alert_rules_active_unique", table_name="alert_rules")
    op.add_column("alert_rules", sa.Column("scope", sa.Text(), server_default="server", nullable=False))
    op.add_column("alert_rules", _group_fk())
    op.add_column("alert_rules", sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False))
    op.alter_column("alert_rules", "server_id", nullable=True)
    op.create_check_constraint("alert_rules_scope_check", "alert_rules", _SCOPE_CHECK)
    # Fails if a server has two active rules for one metric and severity; see the 0.3.0 release notes.
    op.create_index(
        "alert_rules_active_unique", "alert_rules",
        ["scope", sa.text("coalesce(server_id, '')"), sa.text("coalesce(group_id, 0)"), "metric_name", "severity"],
        unique=True, postgresql_where=_NOT_DELETED,
    )
    op.create_index("alert_rules_group_active", "alert_rules", ["group_id"], postgresql_where=_NOT_DELETED)

    # Channels: the same places; a rule-bound channel points at the rule alone.
    op.add_column("alert_channels", sa.Column("scope", sa.Text(), server_default="server", nullable=False))
    op.add_column("alert_channels", _group_fk())
    op.alter_column("alert_channels", "server_id", nullable=True)
    op.create_check_constraint("alert_channels_scope_check", "alert_channels", _SCOPE_CHECK)
    op.create_foreign_key(
        "alert_channels_rule_id_fkey", "alert_channels", "alert_rules", ["rule_id"], ["rule_id"],
        ondelete="CASCADE",
    )
    op.create_index("alert_channels_group_active", "alert_channels", ["group_id"], postgresql_where=_NOT_DELETED)

    # State: one per rule and server.
    op.add_column("alert_state", sa.Column("server_id", sa.Text(), nullable=True))
    op.execute("UPDATE alert_state s SET server_id = r.server_id FROM alert_rules r WHERE r.rule_id = s.rule_id")
    op.alter_column("alert_state", "server_id", nullable=False)
    op.drop_constraint("alert_state_pkey", "alert_state", type_="primary")
    op.create_primary_key("alert_state_pkey", "alert_state", ["rule_id", "server_id"])
    op.drop_index("alert_state_firing", table_name="alert_state")
    op.create_index("alert_state_firing", "alert_state", ["server_id"], postgresql_where=sa.text("state = 'FIRING'"))

    op.create_table(
        "alert_silences",
        sa.Column("silence_id", sa.Uuid(), primary_key=True),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("server_id", sa.Text(), nullable=True),
        _group_fk(),
        sa.Column("rule_id", sa.Uuid(), sa.ForeignKey("alert_rules.rule_id", ondelete="CASCADE"), nullable=True),
        sa.Column("during", postgresql.TSTZRANGE(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("ended_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(_SCOPE_CHECK, name="alert_silences_scope_check"),
        sa.CheckConstraint("btrim(reason) <> ''", name="alert_silences_reason_check"),
        sa.CheckConstraint(_RANGE_IS_BOUNDED, name="alert_silences_during_check"),
    )
    op.create_index("alert_silences_ends", "alert_silences", [sa.text("upper(during)")])

    op.create_table(
        "maintenance_windows",
        sa.Column("window_id", sa.Uuid(), primary_key=True),
        sa.Column("server_id", sa.Text(), sa.ForeignKey("servers.server_id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("during", postgresql.TSTZRANGE(), nullable=True),
        sa.Column("weekdays", postgresql.ARRAY(sa.SmallInteger()), nullable=True),
        sa.Column("local_start", sa.Time(), nullable=True),
        sa.Column("duration", postgresql.INTERVAL(), nullable=True),
        sa.Column("time_zone", sa.Text(), nullable=True),
        sa.Column("repeat_until", sa.Date(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _timestamp("deleted_at", nullable=True),
        sa.CheckConstraint("btrim(reason) <> ''", name="maintenance_windows_reason_check"),
        sa.CheckConstraint(
            "(during IS NOT NULL AND weekdays IS NULL AND local_start IS NULL AND duration IS NULL"
            " AND time_zone IS NULL AND repeat_until IS NULL"
            " AND NOT isempty(during) AND NOT lower_inf(during) AND NOT upper_inf(during))"
            " OR (during IS NULL AND weekdays IS NOT NULL AND cardinality(weekdays) > 0"
            " AND weekdays <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]"
            " AND local_start IS NOT NULL AND time_zone IS NOT NULL"
            " AND duration > interval '0' AND duration <= interval '24 hours')",
            name="maintenance_windows_shape_check",
        ),
    )
    op.create_index(
        "maintenance_windows_server_active", "maintenance_windows", ["server_id"], postgresql_where=_NOT_DELETED,
    )

    op.create_table(
        "maintenance_occurrences",
        sa.Column("occurrence_id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "window_id", sa.Uuid(), sa.ForeignKey("maintenance_windows.window_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("server_id", sa.Text(), nullable=False),
        sa.Column("during", postgresql.TSTZRANGE(), nullable=False),
        sa.CheckConstraint(_RANGE_IS_BOUNDED, name="maintenance_occurrences_during_check"),
        postgresql.ExcludeConstraint(
            ("server_id", "="), ("during", "&&"), name="maintenance_occurrences_no_overlap", using="gist",
        ),
    )
    op.create_index(
        "maintenance_occurrences_window", "maintenance_occurrences", ["window_id", sa.text("lower(during)")],
    )

    for table in _TOUCHED_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_touch_updated_at BEFORE UPDATE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION maestro_touch_updated_at()"
        )
    for table, arguments in _AUDITED.items():
        quoted = ", ".join(f"'{argument}'" for argument in arguments)
        op.execute(
            f"CREATE TRIGGER {table}_audit AFTER INSERT OR UPDATE OR DELETE ON {table}"
            f" FOR EACH ROW EXECUTE FUNCTION maestro_audit_row({quoted})"
        )
        op.execute(
            f"CREATE TRIGGER {table}_audit_truncate BEFORE TRUNCATE ON {table}"
            " FOR EACH STATEMENT EXECUTE FUNCTION maestro_audit_truncate()"
        )


def downgrade() -> None:
    """Back to rules of one server: global and group rules and channels, and the states of
    servers other than the rule's own, are removed."""
    op.drop_table("maintenance_occurrences")
    op.drop_table("maintenance_windows")
    op.drop_table("alert_silences")

    op.execute("DELETE FROM alert_channels WHERE scope <> 'server'")
    op.execute(
        "DELETE FROM alert_state s USING alert_rules r"
        " WHERE r.rule_id = s.rule_id AND (r.scope <> 'server' OR s.server_id <> r.server_id)"
    )
    op.execute("DELETE FROM alert_rules WHERE scope <> 'server'")

    op.drop_index("alert_state_firing", table_name="alert_state")
    op.drop_constraint("alert_state_pkey", "alert_state", type_="primary")
    op.drop_column("alert_state", "server_id")
    op.create_primary_key("alert_state_pkey", "alert_state", ["rule_id"])
    op.create_index("alert_state_firing", "alert_state", ["rule_id"], postgresql_where=sa.text("state = 'FIRING'"))

    op.drop_index("alert_channels_group_active", table_name="alert_channels")
    op.drop_constraint("alert_channels_rule_id_fkey", "alert_channels", type_="foreignkey")
    op.drop_constraint("alert_channels_scope_check", "alert_channels", type_="check")
    op.alter_column("alert_channels", "server_id", nullable=False)
    op.drop_column("alert_channels", "group_id")
    op.drop_column("alert_channels", "scope")

    op.drop_index("alert_rules_group_active", table_name="alert_rules")
    op.drop_index("alert_rules_active_unique", table_name="alert_rules")
    op.drop_constraint("alert_rules_scope_check", "alert_rules", type_="check")
    op.alter_column("alert_rules", "server_id", nullable=False)
    op.drop_column("alert_rules", "enabled")
    op.drop_column("alert_rules", "group_id")
    op.drop_column("alert_rules", "scope")
    op.create_index(
        "alert_rules_active_unique", "alert_rules",
        ["server_id", "metric_name", "operator", "threshold", "severity"],
        unique=True, postgresql_where=_NOT_DELETED,
    )
    op.create_unique_constraint("alert_rules_rule_server_key", "alert_rules", ["rule_id", "server_id"])
    op.create_foreign_key(
        "alert_channels_rule_fkey", "alert_channels", "alert_rules",
        ["rule_id", "server_id"], ["rule_id", "server_id"], ondelete="CASCADE",
    )

    op.drop_table("server_nicknames")
    op.drop_table("servers")  # takes its triggers along
    op.drop_table("server_groups")
    # btree_gist stays: other objects in the database may use it.
