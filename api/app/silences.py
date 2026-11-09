"""Silences: alerts kept quiet on purpose, until a deadline, with a reason and an author.

While a silence covers a server (and, when it names one, a rule), the evaluator still
judges the rules and records the events, but sends no notification. Ending a silence
early moves its end to now; the row stays, so who silenced what remains on record.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import Range, insert
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import AlertSilenceRow, ServerGroupRow, User
from app.rule_scope import Place

REASON_MAX_LENGTH = 500


@dataclass
class Silence:
    silence_id: UUID
    place: Place
    rule_id: UUID | None   # None: every rule
    starts_at: datetime
    ends_at: datetime
    reason: str
    created_by: int
    created_by_name: str
    created_at: datetime
    ended_by: int | None = None

    def covers(self, server_id: str, group_id: int | None, rule_id: UUID) -> bool:
        return self.place.covers(server_id, group_id) and self.rule_id in (None, rule_id)


class UnknownTarget(Exception):
    """The group or rule the silence names does not exist."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _silence(row: AlertSilenceRow, author: str) -> Silence:
    return Silence(
        silence_id=row.silence_id, place=Place(row.scope, row.server_id, row.group_id), rule_id=row.rule_id,
        starts_at=row.during.lower, ends_at=row.during.upper, reason=row.reason, created_by=row.created_by,
        created_by_name=author, created_at=row.created_at, ended_by=row.ended_by,
    )


def _with_author():
    return select(AlertSilenceRow, User.username).join(User, User.id == AlertSilenceRow.created_by)


async def create_silence(
    place: Place, rule_id: UUID | None, starts_at: datetime, ends_at: datetime, reason: str, created_by: int,
) -> Silence:
    if ends_at <= starts_at:
        raise ValueError("A silence must end after it starts")
    silence_id = uuid4()
    try:
        async with db.session() as s:
            if place.group_id is not None and await s.get(ServerGroupRow, place.group_id) is None:
                raise UnknownTarget()
            await s.execute(insert(AlertSilenceRow).values(
                silence_id=silence_id, scope=place.scope, server_id=place.server_id, group_id=place.group_id,
                rule_id=rule_id, during=Range(starts_at, ends_at, bounds="[)"), reason=reason.strip(),
                created_by=created_by,
            ))
    except IntegrityError as exc:
        if "foreign key" in str(exc.orig):
            raise UnknownTarget() from None
        raise
    [silence] = [s for s in await list_silences() if s.silence_id == silence_id]
    return silence


async def list_silences() -> list[Silence]:
    """Silences in force now or still to come, the soonest to end first."""
    async with db.session() as s:
        rows = await s.execute(
            _with_author()
            .where(func.upper(AlertSilenceRow.during) > func.now())
            .order_by(func.upper(AlertSilenceRow.during))
        )
        return [_silence(row, author) for row, author in rows]


async def active_silences() -> list[Silence]:
    """Silences in force at this moment."""
    async with db.session() as s:
        rows = await s.execute(_with_author().where(AlertSilenceRow.during.op("@>")(func.now())))
        return [_silence(row, author) for row, author in rows]


async def end_silence(silence_id: UUID, user_id: int) -> bool:
    """End a silence now (one not started yet ends before it starts). False when there is
    no such silence or it is already over."""
    async with db.session("alert_silences.end") as s:
        ended = await s.scalar(
            update(AlertSilenceRow)
            .where(AlertSilenceRow.silence_id == silence_id, func.upper(AlertSilenceRow.during) > func.now())
            .values(
                # '[]' keeps a silence ended before it started non-empty: one instant, already past.
                during=func.tstzrange(
                    func.least(func.lower(AlertSilenceRow.during), func.now()), func.now(), "[]",
                ),
                ended_by=user_id,
            )
            .returning(AlertSilenceRow.silence_id)
        )
    return ended is not None
