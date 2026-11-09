"""Deliveries that failed, tried again with a growing wait and a limit.

A channel's sender already retries a few times within seconds (app.delivery.post_json).
What still fails is stored here and tried again after 1, 2, 4, 8, 16 and 32 minutes; then
Maestro gives up and logs it. Every attempt is a row in notification_log, as any delivery.

A retry is sent late, so it says how late. When every alert it speaks of has changed
since (its event is no longer the alert's current one), it is dropped instead: a stale
"firing" must not arrive after the "back to normal" that replaced it.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, insert, select, tuple_, update

from app import alert_store, db
from app.clickhouse import AlertEvent, ClickHouseWriter
from app.delivery import Line, Notification
from app.models import AlertStateRow, NotificationRetryRow
from app.notification_dispatcher import dispatch_one
from app.notification_text import delayed_text

logger = logging.getLogger(__name__)

# The wait after each failed attempt; after the last one, Maestro gives up.
RETRY_DELAYS = tuple(timedelta(minutes=m) for m in (1, 2, 4, 8, 16, 32))
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
_BATCH = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _event_dict(event: AlertEvent) -> dict:
    return {
        "event_id": str(event.event_id), "rule_id": str(event.rule_id), "server_id": event.server_id,
        "metric_name": event.metric_name, "value": event.value, "threshold": event.threshold,
        "severity": event.severity, "state": event.state, "triggered_at": event.triggered_at.isoformat(),
    }


def _event(data: dict) -> AlertEvent:
    return AlertEvent(
        event_id=UUID(data["event_id"]), rule_id=UUID(data["rule_id"]), server_id=data["server_id"],
        metric_name=data["metric_name"], value=data["value"], threshold=data["threshold"],
        severity=data["severity"], state=data["state"], triggered_at=datetime.fromisoformat(data["triggered_at"]),
    )


def _lines(stored: list[dict]) -> list[Line]:
    return [Line(kind=d["kind"], text=d["text"], event=_event(d["event"])) for d in stored]


async def schedule(channel_id: UUID, notification: Notification, error: str, now: datetime | None = None) -> None:
    """Keep a delivery that just failed for its first retry. A test is not retried."""
    if not notification.lines:
        return
    now = now or _now()
    async with db.session() as s:
        await s.execute(insert(NotificationRetryRow).values(
            channel_id=channel_id, server_id=notification.server_id, message=notification.text,
            lines=[{"kind": ln.kind, "text": ln.text, "event": _event_dict(ln.event)} for ln in notification.lines],
            attempts=1, next_attempt_at=now + RETRY_DELAYS[0], last_error=error, first_attempt_at=now,
        ))


async def _superseded(lines: list[Line]) -> bool:
    """True when no alert the message speaks of is still at the event it reported."""
    pairs = {(line.event.rule_id, line.event.server_id) for line in lines}
    async with db.session() as s:
        rows = await s.execute(
            select(AlertStateRow.rule_id, AlertStateRow.server_id, AlertStateRow.last_event_id)
            .where(tuple_(AlertStateRow.rule_id, AlertStateRow.server_id).in_(pairs))
        )
        current = {(rule_id, server_id): event_id for rule_id, server_id, event_id in rows}
    return all(current.get((ln.event.rule_id, ln.event.server_id)) != ln.event.event_id for ln in lines)


async def _forget(retry_id: int) -> None:
    async with db.session() as s:
        await s.execute(delete(NotificationRetryRow).where(NotificationRetryRow.retry_id == retry_id))


async def _try_again(row: NotificationRetryRow, writer: ClickHouseWriter, now: datetime) -> None:
    lines = _lines(row.lines)
    if await _superseded(lines):
        logger.info("notification retry %d dropped: its alerts changed since", row.retry_id)
        await _forget(row.retry_id)
        return
    channel = await alert_store.get_channel_by_id(row.channel_id)
    if channel is None:
        await _forget(row.retry_id)
        return
    text = delayed_text(row.message, (now - row.first_attempt_at).total_seconds())
    result = await dispatch_one(channel, Notification.of_lines(row.server_id, lines, text), writer)
    attempts = row.attempts + 1
    if result.ok:
        logger.info("notification retry %d delivered on attempt %d", row.retry_id, attempts)
        await _forget(row.retry_id)
    elif attempts >= MAX_ATTEMPTS:
        logger.error(
            "notification: gave up on %s channel %s for %s after %d attempts (%s)",
            channel.channel_type, channel.channel_id, row.server_id, attempts, result.error,
        )
        await _forget(row.retry_id)
    else:
        async with db.session() as s:
            await s.execute(
                update(NotificationRetryRow)
                .where(NotificationRetryRow.retry_id == row.retry_id)
                .values(attempts=attempts, next_attempt_at=now + RETRY_DELAYS[attempts - 1], last_error=result.error)
            )


async def run_due(writer: ClickHouseWriter, now: datetime | None = None) -> int:
    """Try every retry whose wait is over; returns how many were tried.

    Only the evaluator holding the advisory lock calls it, so no two run at once.
    """
    now = now or _now()
    async with db.session() as s:
        due = list(await s.scalars(
            select(NotificationRetryRow)
            .where(NotificationRetryRow.next_attempt_at <= now)
            .order_by(NotificationRetryRow.next_attempt_at, NotificationRetryRow.retry_id)
            .limit(_BATCH)
        ))
    for row in due:
        try:
            await _try_again(row, writer, now)
        except Exception:
            logger.exception("notification retry %d failed to run", row.retry_id)
    return len(due)


async def pending(server_id: str) -> list[dict]:
    """Retries waiting for this server, for the delivery history on the dashboard."""
    async with db.session() as s:
        rows = await s.scalars(
            select(NotificationRetryRow)
            .where(NotificationRetryRow.server_id == server_id)
            .order_by(NotificationRetryRow.next_attempt_at)
        )
        return [
            {
                "retry_id": r.retry_id, "channel_id": r.channel_id, "attempts": r.attempts,
                "max_attempts": MAX_ATTEMPTS, "next_attempt_at": r.next_attempt_at, "last_error": r.last_error,
                "first_attempt_at": r.first_attempt_at, "kinds": [d["kind"] for d in r.lines],
            }
            for r in rows
        ]


_running: asyncio.Task | None = None


def run_soon(writer: ClickHouseWriter) -> None:
    """Start a pass over the due retries beside the evaluation, unless one is still running."""
    global _running
    if _running is not None and not _running.done():
        return
    _running = asyncio.create_task(run_due(writer))
    _running.add_done_callback(_log_failure)


def _log_failure(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.error("notification retries: pass failed: %s", task.exception())
