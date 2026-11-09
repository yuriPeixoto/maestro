"""Maintenance windows: planned work on a server, once or every week.

Every time a window happens is a row in maintenance_occurrences, where an exclusion
constraint refuses two overlapping occurrences of one server; "in maintenance now" is
`during @> now()`. A weekly window gets its occurrences written HORIZON ahead when it is
created (so an overlap is refused right then) and the worker keeps that horizon ahead.
While a server is in maintenance its rules are judged and events recorded, but nothing
is sent.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.dialects.postgresql import Range, insert
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import MaintenanceOccurrenceRow, MaintenanceWindowRow, ServerRow, User

logger = logging.getLogger(__name__)

HORIZON = timedelta(weeks=8)
MAX_DURATION = timedelta(hours=24)


@dataclass(frozen=True)
class Weekly:
    weekdays: tuple[int, ...]   # ISO: 1 Monday … 7 Sunday
    local_start: time
    duration: timedelta
    time_zone: str
    repeat_until: date | None = None

    def __post_init__(self) -> None:
        if not self.weekdays or not set(self.weekdays) <= set(range(1, 8)):
            raise ValueError("Weekdays go from 1 (Monday) to 7 (Sunday)")
        if not timedelta(0) < self.duration <= MAX_DURATION:
            raise ValueError("A weekly window lasts more than nothing and at most 24 hours")
        try:
            ZoneInfo(self.time_zone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"Unknown time zone {self.time_zone!r}") from None


@dataclass
class MaintenanceWindow:
    window_id: UUID
    server_id: str
    reason: str
    created_by: int
    created_by_name: str
    created_at: datetime
    starts_at: datetime | None       # once
    ends_at: datetime | None
    weekly: Weekly | None
    next_starts_at: datetime | None  # the current or next occurrence
    next_ends_at: datetime | None
    active_now: bool


class Overlap(Exception):
    """The server already has maintenance at that time."""


class UnknownServer(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def weekly_occurrences(weekly: Weekly, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Occurrences that overlap [start, end), as UTC (begin, finish) pairs. The local start
    is read in the window's time zone, so it keeps its wall-clock time across a DST change."""
    zone = ZoneInfo(weekly.time_zone)
    day = start.astimezone(zone).date() - timedelta(days=1)  # one that began yesterday may still run
    last = end.astimezone(zone).date()
    if weekly.repeat_until is not None:
        last = min(last, weekly.repeat_until)
    found = []
    while day <= last:
        if day.isoweekday() in weekly.weekdays:
            begin = datetime.combine(day, weekly.local_start, tzinfo=zone).astimezone(timezone.utc)
            finish = begin + weekly.duration
            if finish > start and begin < end:
                found.append((begin, finish))
        day += timedelta(days=1)
    return found


def _occurrence(window_id: UUID, server_id: str, begin: datetime, finish: datetime) -> dict:
    return {"window_id": window_id, "server_id": server_id, "during": Range(begin, finish, bounds="[)")}


async def create_window(
    server_id: str, reason: str, created_by: int, *,
    once: tuple[datetime, datetime] | None = None, weekly: Weekly | None = None, now: datetime | None = None,
) -> MaintenanceWindow:
    """Raises Overlap when the server has maintenance at any of its times, UnknownServer for a
    server Maestro does not know, ValueError for a window with nothing still to come."""
    if (once is None) == (weekly is None):
        raise ValueError("A window is either once or weekly")
    now = now or _now()
    if once is not None:
        begin, finish = once
        if finish <= begin or finish <= now:
            raise ValueError("A window must end after it starts, and in the future")
        occurrences = [once]
    else:
        occurrences = weekly_occurrences(weekly, now, now + HORIZON)
        if not occurrences:
            raise ValueError("This weekly window has no date left")

    window_id = uuid4()
    values = {"window_id": window_id, "server_id": server_id, "reason": reason.strip(), "created_by": created_by}
    if once is not None:
        values["during"] = Range(*once, bounds="[)")
    else:
        values.update(
            weekdays=sorted(weekly.weekdays), local_start=weekly.local_start, duration=weekly.duration,
            time_zone=weekly.time_zone, repeat_until=weekly.repeat_until,
        )
    try:
        async with db.session() as s:
            if await s.get(ServerRow, server_id) is None:
                raise UnknownServer()
            await s.execute(insert(MaintenanceWindowRow).values(**values))
            await s.execute(
                insert(MaintenanceOccurrenceRow),
                [_occurrence(window_id, server_id, begin, finish) for begin, finish in occurrences],
            )
    except IntegrityError as exc:
        if "maintenance_occurrences_no_overlap" in str(exc.orig):
            raise Overlap() from None
        raise
    [window] = [w for w in await list_windows(server_id) if w.window_id == window_id]
    return window


async def list_windows(server_id: str | None = None) -> list[MaintenanceWindow]:
    """Windows with something still to come (or happening now), the soonest first."""
    upcoming = (
        select(
            MaintenanceOccurrenceRow.window_id,
            func.min(func.lower(MaintenanceOccurrenceRow.during)).label("next_start"),
        )
        .where(func.upper(MaintenanceOccurrenceRow.during) > func.now())
        .group_by(MaintenanceOccurrenceRow.window_id)
        .subquery()
    )
    query = (
        select(MaintenanceWindowRow, User.username, MaintenanceOccurrenceRow.during)
        .join(User, User.id == MaintenanceWindowRow.created_by)
        .join(upcoming, upcoming.c.window_id == MaintenanceWindowRow.window_id)
        .join(MaintenanceOccurrenceRow, and_(
            MaintenanceOccurrenceRow.window_id == MaintenanceWindowRow.window_id,
            func.lower(MaintenanceOccurrenceRow.during) == upcoming.c.next_start,
        ))
        .where(MaintenanceWindowRow.deleted_at.is_(None))
        .order_by(upcoming.c.next_start)
    )
    if server_id is not None:
        query = query.where(MaintenanceWindowRow.server_id == server_id)
    now = _now()
    async with db.session() as s:
        return [_window(row, author, during, now) for row, author, during in await s.execute(query)]


def _weekly(row: MaintenanceWindowRow) -> Weekly | None:
    if row.weekdays is None:
        return None
    return Weekly(
        weekdays=tuple(row.weekdays), local_start=row.local_start, duration=row.duration,
        time_zone=row.time_zone, repeat_until=row.repeat_until,
    )


def _window(row: MaintenanceWindowRow, author: str, next_during: Range, now: datetime) -> MaintenanceWindow:
    weekly = _weekly(row)
    return MaintenanceWindow(
        window_id=row.window_id, server_id=row.server_id, reason=row.reason, created_by=row.created_by,
        created_by_name=author, created_at=row.created_at,
        starts_at=row.during.lower if row.during else None, ends_at=row.during.upper if row.during else None,
        weekly=weekly, next_starts_at=next_during.lower, next_ends_at=next_during.upper,
        active_now=next_during.lower <= now < next_during.upper,
    )


async def cancel_window(window_id: UUID) -> bool:
    """Cancel a window: what is still to come is removed, one happening now ends now."""
    async with db.session("maintenance_windows.cancel") as s:
        cancelled = await s.scalar(
            update(MaintenanceWindowRow)
            .where(MaintenanceWindowRow.window_id == window_id, MaintenanceWindowRow.deleted_at.is_(None))
            .values(deleted_at=func.now())
            .returning(MaintenanceWindowRow.window_id)
        )
        if cancelled is None:
            return False
        mine = MaintenanceOccurrenceRow.window_id == window_id
        await s.execute(delete(MaintenanceOccurrenceRow).where(mine, func.lower(MaintenanceOccurrenceRow.during) >= func.now()))
        await s.execute(
            update(MaintenanceOccurrenceRow)
            .where(mine, MaintenanceOccurrenceRow.during.op("@>")(func.now()))
            .values(during=func.tstzrange(func.lower(MaintenanceOccurrenceRow.during), func.now(), "[)"))
        )
    return True


async def servers_in_maintenance() -> set[str]:
    async with db.session() as s:
        return set(await s.scalars(
            select(MaintenanceOccurrenceRow.server_id).distinct()
            .join(MaintenanceWindowRow, MaintenanceWindowRow.window_id == MaintenanceOccurrenceRow.window_id)
            .where(MaintenanceWindowRow.deleted_at.is_(None), MaintenanceOccurrenceRow.during.op("@>")(func.now()))
        ))


async def extend_weekly_windows(now: datetime | None = None) -> int:
    """Write the occurrences of weekly windows up to HORIZON from now. Returns how many were
    added. One that overlaps other maintenance of its server is skipped and logged."""
    now = now or _now()
    added = 0
    async with db.session() as s:
        rows = await s.execute(
            select(MaintenanceWindowRow, func.max(func.lower(MaintenanceOccurrenceRow.during)))
            .outerjoin(MaintenanceOccurrenceRow, MaintenanceOccurrenceRow.window_id == MaintenanceWindowRow.window_id)
            .where(MaintenanceWindowRow.deleted_at.is_(None), MaintenanceWindowRow.weekdays.is_not(None))
            .group_by(MaintenanceWindowRow.window_id)
        )
        for row, last_start in rows.all():
            for begin, finish in weekly_occurrences(_weekly(row), now, now + HORIZON):
                if last_start is not None and begin <= last_start:
                    continue
                inserted = await s.scalar(
                    insert(MaintenanceOccurrenceRow)
                    .values(**_occurrence(row.window_id, row.server_id, begin, finish))
                    .on_conflict_do_nothing()
                    .returning(MaintenanceOccurrenceRow.occurrence_id)
                )
                if inserted is None:
                    logger.warning(
                        "maintenance: window %s on %s skips %s, which overlaps other maintenance",
                        row.window_id, row.server_id, begin.isoformat(),
                    )
                    continue
                added += 1
    return added
