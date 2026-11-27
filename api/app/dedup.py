"""Write each agent message once, whichever path it came by.

The agent gives every message an id (UUIDv7) and, on `transport: both`, sends it through Redis
and through NATS. Before a batch is written to ClickHouse its ids are claimed in
`ingested_messages`, in the same Postgres transaction that stays open while ClickHouse writes:

- a failed write rolls the claim back, so the redelivered message is written later;
- two paths claiming one id at the same moment: the second waits on the first's row lock, and
  drops the message once the first commits (or writes it, if the first rolled back);
- a message redelivered after its claim committed (the ack was lost) is dropped.

What is left is the moment between the ClickHouse write and the commit: a crash there writes the
message twice, as a crash between the write and the ack always did.

Redis carries one message as many entries (one per metric or log line) that can arrive in
different reads, so an id Redis itself claimed is the rest of that message and is written; only
an id NATS claimed is dropped on the Redis path. NATS carries a message whole, and drops any id
already claimed.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, TypeVar
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import db

logger = logging.getLogger(__name__)

Source = Literal["redis", "nats"]
Kind = Literal["metrics", "logs"]
Row = TypeVar("Row")

# Longer than the agent's disk buffer usually holds a message back, and than the streams keep one.
RETENTION = timedelta(days=7)
PURGE_INTERVAL_SECONDS = 3600
COUNTS_INTERVAL_SECONDS = 60
_PURGE_CHUNK = 10_000

_CLAIM = text("""
    INSERT INTO ingested_messages (msg_id, source, kind)
    SELECT unnest(CAST(:ids AS uuid[])), :source, :kind
    ON CONFLICT (msg_id) DO NOTHING
    RETURNING msg_id
""")
_CLAIMED_BY_REDIS = text("""
    SELECT msg_id FROM ingested_messages WHERE msg_id = ANY(CAST(:ids AS uuid[])) AND source = 'redis'
""")
_PURGE = text("""
    DELETE FROM ingested_messages
    WHERE msg_id IN (
        SELECT msg_id FROM ingested_messages WHERE received_at < now() - CAST(:age AS interval) LIMIT :chunk
    )
""")


def parse_id(raw: object) -> UUID | None:
    """The message id, or None for a message without one (an agent older than 0.4.0)."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


async def claim(session: AsyncSession, ids: set[UUID], source: Source, kind: Kind) -> set[UUID]:
    """The ids among `ids` this batch should write. Call inside the transaction that writes them."""
    if not ids:
        return set()
    params = {"ids": sorted(ids), "source": source, "kind": kind}
    new = set((await session.scalars(_CLAIM, params)).all())
    taken = ids - new
    if source == "redis" and taken:
        new |= set((await session.scalars(_CLAIMED_BY_REDIS, {"ids": sorted(taken)})).all())
    return new


async def write_once(
    items: list[tuple[UUID | None, list[Row]]],
    source: Source,
    kind: Kind,
    insert: Callable[[list[Row]], Awaitable[None]],
) -> int:
    """Write the rows of each (message id, rows) item whose id this path may write, and return
    how many rows were written. Raises when the insert fails: nothing is claimed then.

    Several items may share an id (Redis entries of one message). An item without an id comes
    from an agent older than 0.4.0 and is always written.
    """
    ids = {msg_id for msg_id, _ in items if msg_id is not None}
    received = sum(len(item_rows) for _, item_rows in items)
    if not ids:
        rows = [row for _, item_rows in items for row in item_rows]
        await insert(rows)
        _counts[(source, kind)].add(received=received, written=len(rows))
        return len(rows)

    async with db.session() as session:
        allowed = await claim(session, ids, source, kind)
        rows = [row for msg_id, item_rows in items if msg_id is None or msg_id in allowed for row in item_rows]
        await insert(rows)
    _counts[(source, kind)].add(received=received, written=len(rows))
    return len(rows)


async def purge_expired() -> int:
    """Forget ids older than RETENTION, in chunks so no single statement holds the table long."""
    params = {"age": RETENTION, "chunk": _PURGE_CHUNK}
    removed = 0
    while True:
        async with db.session() as session:
            result = await session.execute(_PURGE, params)
        removed += result.rowcount
        if result.rowcount < _PURGE_CHUNK:
            return removed


async def run_purge(on_cycle: Callable[[], None] = lambda: None) -> None:
    while True:
        removed = await purge_expired()
        if removed:
            logger.info("dedup: forgot %d message ids older than %s", removed, RETENTION)
        on_cycle()
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)


# ── What each path brought, for comparing them during the parallel run ────────


@dataclass
class _Counts:
    received: int = 0  # rows (metrics or log lines) that reached this path
    written: int = 0  # of those, rows written to ClickHouse; the rest another path wrote first

    def add(self, received: int, written: int) -> None:
        self.received += received
        self.written += written


_counts: defaultdict[tuple[Source, Kind], _Counts] = defaultdict(_Counts)


def take_counts() -> dict[tuple[Source, Kind], _Counts]:
    """What arrived since the last call, per path and kind, and start counting again."""
    taken = dict(_counts)
    _counts.clear()
    return taken


async def log_counts_forever(process: str) -> None:
    """One line per path and kind every minute: rows received and rows written. On
    `transport: both` both paths receive the same rows (give or take what is in flight), and
    together write each of them once."""
    while True:
        await asyncio.sleep(COUNTS_INTERVAL_SECONDS)
        for (source, kind), counts in sorted(take_counts().items()):
            logger.info(
                "ingest-counts %s source=%s kind=%s received=%d written=%d",
                process, source, kind, counts.received, counts.written,
            )
