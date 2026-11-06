"""Roles, deactivation, last access and the audit log; password reset tokens removed.

Accounts that exist before this revision become admins (one could do everything
until now); new accounts start as viewers.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-09
"""
from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url

from app.config import settings

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Trigger arguments per audited table: the key column, then "skip:<column>" for columns
# whose change alone is not worth a row, and "secret:<column>" for values never copied
# into the log (only whether they changed).
_AUDITED = {
    "users": (
        "id",
        "skip:updated_at", "skip:last_seen_version", "skip:failed_login_count",
        "skip:last_failed_login_at", "skip:locked_until", "skip:last_login_at", "skip:last_seen_at",
        "secret:password_hash",
    ),
    "alert_rules": ("rule_id", "skip:updated_at"),
    "alert_channels": ("channel_id", "skip:updated_at", "secret:config"),
}

_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_$]{0,62}$")


def _api_role() -> str:
    """The database user the API connects as: only its transactions may say who the
    caller is. `-x api_role=NAME` when migrating as another user; otherwise the user
    in the database URL (the API's own, in MAESTRO_DATABASE_URL)."""
    role = context.get_x_argument(as_dictionary=True).get("api_role")
    if not role:
        url = context.config.attributes.get("database_url") or settings.database_url
        role = make_url(url).username or ""
    if not _ROLE_NAME.match(role):
        raise RuntimeError(f"Invalid API database user {role!r}; pass -x api_role=<name>")
    return role


_AUDIT_FUNCTION = r"""
CREATE FUNCTION maestro_audit_row() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    key_column text := TG_ARGV[0];
    argument text;
    skipped text[] := '{}';
    secrets text[] := '{}';
    old_doc jsonb;
    new_doc jsonb;
    column_name text;
    -- Who the API says the caller is counts only on the API's own connections. Anyone
    -- else can set these settings too, so for them the log names the database user,
    -- the client program and the address the connection came from.
    from_api boolean := session_user = maestro_audit_api_role();
    actor_name text;
    action_name text;
    actor_id bigint;
    caller_ip inet;
    caller_agent text;
BEGIN
    IF from_api THEN
        actor_name := nullif(current_setting('maestro.actor', true), '');
        action_name := nullif(current_setting('maestro.action', true), '');
        actor_id := nullif(current_setting('maestro.actor_id', true), '')::bigint;
        caller_ip := nullif(current_setting('maestro.ip', true), '')::inet;
        caller_agent := nullif(current_setting('maestro.user_agent', true), '');
    ELSE
        caller_ip := inet_client_addr();
    END IF;

    FOREACH argument IN ARRAY TG_ARGV[1:] LOOP
        IF argument LIKE 'skip:%' THEN
            skipped := skipped || substr(argument, 6);
        ELSIF argument LIKE 'secret:%' THEN
            secrets := secrets || substr(argument, 8);
        END IF;
    END LOOP;

    IF TG_OP <> 'INSERT' THEN old_doc := to_jsonb(OLD) - skipped; END IF;
    IF TG_OP <> 'DELETE' THEN new_doc := to_jsonb(NEW) - skipped; END IF;
    IF TG_OP = 'UPDATE' AND old_doc = new_doc THEN
        RETURN NULL;
    END IF;

    FOREACH column_name IN ARRAY secrets LOOP
        IF old_doc IS NOT NULL AND new_doc IS NOT NULL AND old_doc -> column_name IS DISTINCT FROM new_doc -> column_name THEN
            new_doc := jsonb_set(new_doc, ARRAY[column_name], '"[changed]"');
        ELSIF new_doc ? column_name THEN
            new_doc := jsonb_set(new_doc, ARRAY[column_name], '"[redacted]"');
        END IF;
        IF old_doc ? column_name THEN
            old_doc := jsonb_set(old_doc, ARRAY[column_name], '"[redacted]"');
        END IF;
    END LOOP;

    INSERT INTO audit_log (actor_user_id, actor, source_ip, user_agent, action, target_table, target_id, before, after)
    VALUES (
        actor_id,
        coalesce(actor_name, session_user || ' via ' || coalesce(nullif(current_setting('application_name', true), ''), 'unknown')),
        caller_ip,
        caller_agent,
        coalesce(action_name, TG_TABLE_NAME || '.' || lower(TG_OP)),
        TG_TABLE_NAME,
        coalesce(new_doc, old_doc) ->> key_column,
        old_doc,
        new_doc
    );
    RETURN NULL;
END;
$$
"""

# TRUNCATE fires no row trigger: one entry for the statement, with the row count it removes.
_TRUNCATE_FUNCTION = r"""
CREATE FUNCTION maestro_audit_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    removed bigint;
BEGIN
    EXECUTE format('SELECT count(*) FROM %I', TG_TABLE_NAME) INTO removed;
    INSERT INTO audit_log (actor, source_ip, action, target_table, after)
    VALUES (
        session_user || ' via ' || coalesce(nullif(current_setting('application_name', true), ''), 'unknown'),
        inet_client_addr(),
        TG_TABLE_NAME || '.truncate',
        TG_TABLE_NAME,
        jsonb_build_object('rows', removed)
    );
    RETURN NULL;
END;
$$
"""

# The log is only ever added to: not even the API's own database user may rewrite or
# remove an entry (its default privileges include UPDATE and DELETE on every table).
_APPEND_ONLY_FUNCTION = r"""
CREATE FUNCTION maestro_audit_log_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only' USING ERRCODE = 'insufficient_privilege';
    RETURN NULL;
END;
$$
"""


def upgrade() -> None:
    # Existing accounts could do everything: they keep that as admins. The default is
    # changed to viewer right after, for accounts created from now on.
    op.add_column("users", sa.Column("role", sa.Text(), server_default="admin", nullable=False))
    op.alter_column("users", "role", server_default="viewer")
    op.create_check_constraint("users_role_check", "users", "role IN ('viewer', 'operator', 'admin')")
    op.add_column("users", sa.Column("full_name", sa.Text(), nullable=True))
    for column in ("deactivated_at", "last_login_at", "last_seen_at", "sessions_valid_after"):
        op.add_column("users", sa.Column(column, sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("source_ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_table", sa.Text(), nullable=True),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint("action <> ''", name="audit_log_action_check"),
    )
    op.create_index("ix_audit_log_occurred_at", "audit_log", [sa.text("occurred_at DESC")])
    op.create_index("ix_audit_log_actor_user_id", "audit_log", ["actor_user_id", sa.text("id DESC")])
    op.create_index("ix_audit_log_action", "audit_log", ["action", sa.text("id DESC")])

    op.execute(_APPEND_ONLY_FUNCTION)
    op.execute(
        "CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log"
        " FOR EACH ROW EXECUTE FUNCTION maestro_audit_log_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log"
        " FOR EACH STATEMENT EXECUTE FUNCTION maestro_audit_log_append_only()"
    )

    # Changing it is DDL: only the owner can say which connections speak for the API.
    op.execute(
        "CREATE FUNCTION maestro_audit_api_role() RETURNS name LANGUAGE sql IMMUTABLE"
        f" AS $$ SELECT '{_api_role()}'::name $$"
    )
    op.execute(_AUDIT_FUNCTION)
    op.execute(_TRUNCATE_FUNCTION)
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

    # Only the SMTP forgot-password flow used them; resets are a temporary password from an admin now.
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")


def downgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("token", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])

    for table in _AUDITED:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_audit ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_audit_truncate ON {table}")
    op.execute("DROP FUNCTION IF EXISTS maestro_audit_row()")
    op.execute("DROP FUNCTION IF EXISTS maestro_audit_truncate()")
    op.execute("DROP FUNCTION IF EXISTS maestro_audit_api_role()")
    op.drop_table("audit_log")  # takes its append-only trigger along
    op.execute("DROP FUNCTION IF EXISTS maestro_audit_log_append_only()")

    for column in ("sessions_valid_after", "last_seen_at", "last_login_at", "deactivated_at", "full_name"):
        op.drop_column("users", column)
    op.drop_constraint("users_role_check", "users", type_="check")
    op.drop_column("users", "role")
