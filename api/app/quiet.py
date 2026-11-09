"""Whether an alert may notify now: not while its server is in maintenance or a silence covers it."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import UUID

from app import maintenance, silences
from app.silences import Silence

REASON_MAINTENANCE = "maintenance"
REASON_SILENCE = "silence"


@dataclass
class QuietNow:
    silences: list[Silence] = field(default_factory=list)
    in_maintenance: set[str] = field(default_factory=set)

    def reason(self, server_id: str, group_id: int | None, rule_id: UUID) -> str | None:
        """Why an alert of this rule on this server must not notify, or None."""
        if server_id in self.in_maintenance:
            return REASON_MAINTENANCE
        if any(s.covers(server_id, group_id, rule_id) for s in self.silences):
            return REASON_SILENCE
        return None


async def quiet_now() -> QuietNow:
    active, in_maintenance = await asyncio.gather(silences.active_silences(), maintenance.servers_in_maintenance())
    return QuietNow(active, in_maintenance)
