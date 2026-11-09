"""Silences and maintenance windows: alerts that are judged and recorded but not sent."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, model_validator

from app import alert_store, maintenance, silences
from app.auth import require
from app.logs import _utc_iso
from app.maintenance import MaintenanceWindow, Weekly
from app.permissions import Permission
from app.scoped_alerts import PlaceIn
from app.silences import REASON_MAX_LENGTH, Silence

router = APIRouter(prefix="/alerts", tags=["alerts"])

_manage = require(Permission.MANAGE_ALERTS)
_MAX_SILENCE = timedelta(days=30)
_MAX_ONE_OFF_WINDOW = timedelta(days=7)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ── Silences ──────────────────────────────────────────────────────────────────

class SilenceIn(PlaceIn):
    rule_id: UUID | None = None   # None: every rule
    starts_at: datetime | None = None   # None: now
    ends_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=int(_MAX_SILENCE.total_seconds() // 60))
    reason: str = Field(min_length=1, max_length=REASON_MAX_LENGTH)

    @model_validator(mode="after")
    def _one_deadline(self):
        if (self.ends_at is None) == (self.duration_minutes is None):
            raise ValueError("Give either ends_at or duration_minutes")
        if not self.reason.strip():
            raise ValueError("A silence needs a reason")
        return self


class SilenceOut(BaseModel):
    silence_id: str
    scope: str
    server_id: str | None
    group_id: int | None
    rule_id: str | None
    starts_at: str
    ends_at: str
    reason: str
    created_by: str
    created_at: str
    active: bool


def _silence_out(s: Silence, now: datetime) -> SilenceOut:
    return SilenceOut(
        silence_id=str(s.silence_id), scope=s.place.scope, server_id=s.place.server_id, group_id=s.place.group_id,
        rule_id=str(s.rule_id) if s.rule_id else None, starts_at=_utc_iso(s.starts_at), ends_at=_utc_iso(s.ends_at),
        reason=s.reason, created_by=s.created_by_name, created_at=_utc_iso(s.created_at),
        active=s.starts_at <= now < s.ends_at,
    )


@router.get("/silences", response_model=list[SilenceOut])
async def list_silences() -> list[SilenceOut]:
    """Silences in force or still to come."""
    now = datetime.now(timezone.utc)
    return [_silence_out(s, now) for s in await silences.list_silences()]


@router.post("/silences", response_model=SilenceOut, status_code=201)
async def create_silence(body: SilenceIn, user: dict = Depends(_manage)) -> SilenceOut:
    now = datetime.now(timezone.utc)
    starts_at = _aware(body.starts_at) if body.starts_at else now
    ends_at = _aware(body.ends_at) if body.ends_at else starts_at + timedelta(minutes=body.duration_minutes)
    if ends_at <= max(starts_at, now):
        raise HTTPException(status_code=422, detail="A silence must end in the future, after it starts")
    if ends_at - starts_at > _MAX_SILENCE:
        raise HTTPException(status_code=422, detail="A silence lasts at most 30 days; plan maintenance instead")
    if body.rule_id is not None and await alert_store.get_rule(body.rule_id) is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    try:
        silence = await silences.create_silence(body.place(), body.rule_id, starts_at, ends_at, body.reason, user["id"])
    except silences.UnknownTarget:
        raise HTTPException(status_code=404, detail="Group or rule not found") from None
    return _silence_out(silence, now)


@router.post("/silences/{silence_id}/end", status_code=204)
async def end_silence(silence_id: UUID, user: dict = Depends(_manage)) -> Response:
    if not await silences.end_silence(silence_id, user["id"]):
        raise HTTPException(status_code=404, detail="No silence in force or to come with this id")
    return Response(status_code=204)


# ── Maintenance ───────────────────────────────────────────────────────────────

class WeeklyIn(BaseModel):
    weekdays: list[int] = Field(min_length=1, max_length=7)   # ISO: 1 Monday … 7 Sunday
    local_start: time
    duration_minutes: int = Field(ge=1, le=24 * 60)
    time_zone: str = Field(min_length=1, max_length=64)
    repeat_until: date | None = None


class MaintenanceIn(BaseModel):
    server_id: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=REASON_MAX_LENGTH)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    weekly: WeeklyIn | None = None

    @model_validator(mode="after")
    def _once_or_weekly(self):
        once = self.starts_at is not None and self.ends_at is not None
        if once == (self.weekly is not None) or (not once and (self.starts_at or self.ends_at)):
            raise ValueError("Give starts_at and ends_at for one window, or weekly for a recurring one")
        if not self.reason.strip():
            raise ValueError("A window needs a reason")
        return self


class WeeklyOut(BaseModel):
    weekdays: list[int]
    local_start: str
    duration_minutes: int
    time_zone: str
    repeat_until: str | None


class MaintenanceOut(BaseModel):
    window_id: str
    server_id: str
    reason: str
    created_by: str
    created_at: str
    starts_at: str | None
    ends_at: str | None
    weekly: WeeklyOut | None
    next_starts_at: str | None
    next_ends_at: str | None
    active: bool


def _window_out(w: MaintenanceWindow) -> MaintenanceOut:
    weekly = None
    if w.weekly is not None:
        weekly = WeeklyOut(
            weekdays=list(w.weekly.weekdays), local_start=w.weekly.local_start.strftime("%H:%M"),
            duration_minutes=int(w.weekly.duration.total_seconds() // 60), time_zone=w.weekly.time_zone,
            repeat_until=w.weekly.repeat_until.isoformat() if w.weekly.repeat_until else None,
        )
    return MaintenanceOut(
        window_id=str(w.window_id), server_id=w.server_id, reason=w.reason, created_by=w.created_by_name,
        created_at=_utc_iso(w.created_at),
        starts_at=_utc_iso(w.starts_at) if w.starts_at else None, ends_at=_utc_iso(w.ends_at) if w.ends_at else None,
        weekly=weekly,
        next_starts_at=_utc_iso(w.next_starts_at) if w.next_starts_at else None,
        next_ends_at=_utc_iso(w.next_ends_at) if w.next_ends_at else None,
        active=w.active_now,
    )


@router.get("/maintenance", response_model=list[MaintenanceOut])
async def list_maintenance(server_id: str | None = None) -> list[MaintenanceOut]:
    """Windows happening now or still to come, the soonest first."""
    return [_window_out(w) for w in await maintenance.list_windows(server_id)]


@router.post("/maintenance", response_model=MaintenanceOut, status_code=201)
async def create_maintenance(body: MaintenanceIn, user: dict = Depends(_manage)) -> MaintenanceOut:
    once = weekly = None
    try:
        if body.weekly is None:
            once = (_aware(body.starts_at), _aware(body.ends_at))
            if once[1] - once[0] > _MAX_ONE_OFF_WINDOW:
                raise HTTPException(status_code=422, detail="One window lasts at most 7 days")
        else:
            weekly = Weekly(
                weekdays=tuple(sorted(set(body.weekly.weekdays))), local_start=body.weekly.local_start,
                duration=timedelta(minutes=body.weekly.duration_minutes), time_zone=body.weekly.time_zone,
                repeat_until=body.weekly.repeat_until,
            )
        window = await maintenance.create_window(body.server_id, body.reason, user["id"], once=once, weekly=weekly)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except maintenance.UnknownServer:
        raise HTTPException(status_code=404, detail="Server not found") from None
    except maintenance.Overlap:
        raise HTTPException(
            status_code=409, detail="This server already has maintenance planned at that time",
        ) from None
    return _window_out(window)


@router.delete("/maintenance/{window_id}", status_code=204, dependencies=[Depends(_manage)])
async def cancel_maintenance(window_id: UUID) -> Response:
    if not await maintenance.cancel_window(window_id):
        raise HTTPException(status_code=404, detail="Window not found")
    return Response(status_code=204)
