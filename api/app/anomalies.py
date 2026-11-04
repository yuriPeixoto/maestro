"""Anomaly episodes: when a server left its normal range for the hour, and how."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.anomaly_store import list_episodes

router = APIRouter(prefix="/anomalies", tags=["anomalies"])

_MAX_HOURS = 30 * 24
# The worker rewrites a running episode every minute; one that has not moved for
# longer than this ended without a final write (worker restart) and is not "ongoing".
_ONGOING_GRACE = timedelta(minutes=5)


class DeviationOut(BaseModel):
    metric: str
    value: float
    z: float
    normal_low: float
    normal_high: float
    peak_at: str


class EpisodeOut(BaseModel):
    started_at: str
    ended_at: str
    minutes: int
    ongoing: bool
    deviations: list[DeviationOut]


def _iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@router.get("/{server_id}/episodes", response_model=list[EpisodeOut])
async def get_episodes(
    server_id: str,
    request: Request,
    hours: int = Query(default=24 * 7, ge=1, le=_MAX_HOURS),
) -> list[EpisodeOut]:
    """Episodes still running at some point in the last `hours`, newest first."""
    now = datetime.now(timezone.utc)
    records = await list_episodes(request.app.state.ch_client, server_id, now - timedelta(hours=hours))
    out = []
    for record in records:
        ended = record.ended_at if record.ended_at.tzinfo else record.ended_at.replace(tzinfo=timezone.utc)
        started = record.started_at if record.started_at.tzinfo else record.started_at.replace(tzinfo=timezone.utc)
        out.append(EpisodeOut(
            started_at=_iso(started),
            ended_at=_iso(ended),
            minutes=int((ended - started) / timedelta(minutes=1)),
            ongoing=record.is_open and now - ended <= _ONGOING_GRACE,
            deviations=[DeviationOut(**d) for d in record.deviations],
        ))
    return out
