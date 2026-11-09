"""The alert cycle: acknowledging, "no data", what the channels were last told, and
deliveries waiting to be retried.

`notified_state` is what the channels last heard about a rule on a server. The evaluator
announces whenever the state differs from it and nothing keeps the alert quiet, so an
alert that changed during a silence or maintenance is announced when the quiet ends.
Existing rows were announced as they stand, so it starts equal to `state`.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-09
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATES = "('INACTIVE', 'FIRING', 'RESOLVED', 'NO_DATA')"
_OLD_STATES = "('INACTIVE', 'FIRING', 'RESOLVED')"


def upgrade() -> None:
    op.drop_constraint("alert_state_state_check", "alert_state", type_="check")
    op.create_check_constraint("alert_state_state_check", "alert_state", f"state IN {_STATES}")
    op.add_column("alert_state", sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("alert_state", sa.Column("notified_state", sa.Text(), nullable=True))
    op.add_column("alert_state", sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("alert_state", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "alert_state",
        sa.Column("acknowledged_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_check_constraint(
        "alert_state_notified_state_check", "alert_state",
        f"notified_state IS NULL OR notified_state IN {_STATES}",
    )
    op.create_check_constraint(
        "alert_state_acknowledged_check", "alert_state",
        "(acknowledged_at IS NULL) = (acknowledged_by IS NULL)",
    )
    op.execute(
        "UPDATE alert_state SET notified_state = state, changed_at = greatest(last_fired_at, last_resolved_at),"
        " last_notified_at = CASE WHEN state = 'FIRING' THEN last_fired_at ELSE last_resolved_at END"
    )

    op.create_table(
        "notification_retries",
        sa.Column("retry_id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column(
            "channel_id", sa.Uuid(),
            sa.ForeignKey("alert_channels.channel_id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("server_id", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("lines", postgresql.JSONB(), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("first_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts >= 1", name="notification_retries_attempts_check"),
        sa.CheckConstraint(
            "jsonb_typeof(lines) = 'array' AND jsonb_array_length(lines) > 0",
            name="notification_retries_lines_check",
        ),
    )
    op.create_index("notification_retries_due", "notification_retries", ["next_attempt_at"])
    op.create_index("notification_retries_channel", "notification_retries", ["channel_id"])


def downgrade() -> None:
    """NO_DATA rows go back to INACTIVE; waiting retries are dropped (their failures stay in notification_log)."""
    op.drop_index("notification_retries_channel", table_name="notification_retries")
    op.drop_index("notification_retries_due", table_name="notification_retries")
    op.drop_table("notification_retries")

    op.drop_constraint("alert_state_acknowledged_check", "alert_state", type_="check")
    op.drop_constraint("alert_state_notified_state_check", "alert_state", type_="check")
    op.drop_column("alert_state", "acknowledged_by")
    op.drop_column("alert_state", "acknowledged_at")
    op.drop_column("alert_state", "last_notified_at")
    op.drop_column("alert_state", "notified_state")
    op.drop_column("alert_state", "changed_at")
    op.execute("UPDATE alert_state SET state = 'INACTIVE' WHERE state = 'NO_DATA'")
    op.drop_constraint("alert_state_state_check", "alert_state", type_="check")
    op.create_check_constraint("alert_state_state_check", "alert_state", f"state IN {_OLD_STATES}")
