"""GET /audit: the audit log, for admins."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app import audit
from app.auth import require
from app.permissions import Permission

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(require(Permission.VIEW_AUDIT))])

_PAGE_DEFAULT = 50
_PAGE_MAX = 200


class AuditEntryOut(BaseModel):
    id: int
    occurred_at: str
    actor_user_id: int | None
    actor: str
    source_ip: str | None
    user_agent: str | None
    action: str
    target_table: str | None
    target_id: str | None
    before: dict | None
    after: dict | None
    # What the target is, for the screen ({"kind": "user" | "rule" | "channel", ...}), as
    # the entry's own row had it; null when the entry has no target or the row is gone.
    target_info: dict | None = None


class AuditPageOut(BaseModel):
    entries: list[AuditEntryOut]
    # Pass as before_id for the next (older) page; null on the last one.
    next_before_id: int | None


@router.get("", response_model=AuditPageOut)
async def list_audit(
    actor_user_id: int | None = None,
    outside: bool = Query(default=False, description="Only changes no account made (straight in the database)"),
    by_worker: bool = Query(default=False, description="Only what Maestro's worker did on its own"),
    action: str | None = Query(default=None, description='Exact name, or a prefix ending in "." (e.g. "users.")'),
    target_table: str | None = None,
    target_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    before_id: int | None = None,
    limit: int = Query(default=_PAGE_DEFAULT, ge=1, le=_PAGE_MAX),
) -> AuditPageOut:
    rows = await audit.list_entries(
        actor_user_id=actor_user_id, outside=outside, by_worker=by_worker, action=action, target_table=target_table,
        target_id=target_id, since=since, until=until, before_id=before_id, limit=limit + 1,
    )
    page, more = rows[:limit], len(rows) > limit
    targets = await audit.describe_targets(page)
    return AuditPageOut(
        entries=[
            AuditEntryOut(
                **row, target_info=audit.target_as_it_was(row, targets.get((row["target_table"], row["target_id"]))),
            )
            for row in page
        ],
        next_before_id=page[-1]["id"] if more else None,
    )
