"""Ingestion from NATS (ADR-015): what was already written, the processes' health, and what the
agents send on their events subject.

- `ingested_messages`: the ids of agent messages already written to ClickHouse, so that a message
  arriving through Redis and through NATS (agent on `transport: both`) is written once.
- `process_health`: one row per Maestro process (worker, ingest) with its task reports, read by
  /health. Replaces the `maestro:worker:health` key in Redis.
- `agents`, `server_packages`, `db_snapshots`: the agent registry, the OS package snapshot and the
  database connection lists, from the `events` subject. They were Redis hashes.

All new tables start empty: nothing is copied from Redis, the agents send all of it again.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-27
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingested_messages",
        sa.Column("msg_id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("source IN ('redis', 'nats')", name="ingested_messages_source_check"),
        sa.CheckConstraint("kind IN ('metrics', 'logs')", name="ingested_messages_kind_check"),
    )
    op.create_index("ingested_messages_received", "ingested_messages", ["received_at"])

    op.create_table(
        "process_health",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tasks", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("jsonb_typeof(tasks) = 'array'", name="process_health_tasks_check"),
    )

    op.create_table(
        "agents",
        sa.Column("server_id", sa.Text(), primary_key=True),
        sa.Column("hostname", sa.Text(), nullable=False),
        sa.Column("os", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=False),
        sa.Column("agent_version", sa.Text(), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deregistered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("jsonb_typeof(tags) = 'array'", name="agents_tags_check"),
    )

    op.create_table(
        "server_packages",
        sa.Column("server_id", sa.Text(), primary_key=True),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("jsonb_typeof(snapshot) = 'object'", name="server_packages_snapshot_check"),
    )

    op.create_table(
        "db_snapshots",
        sa.Column("server_id", sa.Text(), primary_key=True),
        sa.Column("db_type", sa.Text(), primary_key=True),
        sa.Column("connections", postgresql.JSONB(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("jsonb_typeof(connections) = 'array'", name="db_snapshots_connections_check"),
    )


def downgrade() -> None:
    """Drops the tables. The agents write the registry, packages and connection lists again; 0005's
    worker reads its health from Redis and ignores the claimed ids."""
    op.drop_table("db_snapshots")
    op.drop_table("server_packages")
    op.drop_table("agents")
    op.drop_table("process_health")
    op.drop_index("ingested_messages_received", table_name="ingested_messages")
    op.drop_table("ingested_messages")
