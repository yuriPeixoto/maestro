"""The one definition of a server's state.

The dashboard and the alert screen both read this result, so they cannot
disagree. The state is the worst of two inputs: the default limits below, which
cover servers with no rule yet, and the alert rules firing right now.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from app.config import settings

_ABOVE_AVERAGE_MIN_POINTS = 5
_ABOVE_AVERAGE_FACTOR = 1.10


@dataclass(frozen=True)
class MetricLimits:
    attention: float
    critical: float


@dataclass(frozen=True)
class Readings:
    cpu: float | None
    memory: float | None
    disk: float | None

    @property
    def empty(self) -> bool:
        return self.cpu is None and self.memory is None and self.disk is None


@dataclass(frozen=True)
class Headline:
    code: str
    params: dict[str, float] = field(default_factory=dict)


def cpu_limits() -> MetricLimits:
    return MetricLimits(settings.health_cpu_attention_percent, settings.health_cpu_critical_percent)


def memory_limits() -> MetricLimits:
    return MetricLimits(settings.health_memory_attention_percent, settings.health_memory_critical_percent)


def disk_limits() -> MetricLimits:
    return MetricLimits(settings.health_disk_attention_percent, settings.health_disk_critical_percent)


def _reaches(value: float | None, limit: float) -> bool:
    return value is not None and value >= limit


def _breaches(readings: Readings, level: str) -> bool:
    pairs = (
        (readings.cpu, cpu_limits()),
        (readings.memory, memory_limits()),
        (readings.disk, disk_limits()),
    )
    return any(_reaches(value, getattr(limits, level)) for value, limits in pairs)


def health_state(
    server_status: str,
    readings: Readings,
    memory_rising: bool,
    open_alert_severities: Iterable[str],
) -> str:
    """Return "ok", "attention", "critical" or "quiet" (no data to judge on)."""
    severities = list(open_alert_severities)
    if server_status == "offline":
        return "critical"
    if readings.empty:
        return "quiet"
    if _breaches(readings, "critical") or "critical" in severities:
        return "critical"
    if severities or memory_rising or _breaches(readings, "attention"):
        return "attention"
    return "ok"


def health_headline(
    server_status: str,
    readings: Readings,
    cpu_baseline: float | None,
    memory_projection_hours: int | None,
    open_alert_count: int,
) -> Headline:
    """Return a translatable code for the sentence that explains the state."""
    if server_status == "offline":
        return Headline("offline")
    if readings.empty:
        return Headline("no_data")

    critical_checks = (
        ("cpu_critical", readings.cpu, cpu_limits()),
        ("memory_critical", readings.memory, memory_limits()),
        ("disk_critical", readings.disk, disk_limits()),
    )
    for code, value, limits in critical_checks:
        if _reaches(value, limits.critical):
            return Headline(code, {"value": round(value, 1)})

    if open_alert_count:
        return Headline("alerts_firing", {"count": open_alert_count})
    if memory_projection_hours is not None:
        return Headline(
            "memory_rising",
            {"threshold": round(memory_limits().critical), "hours": memory_projection_hours},
        )
    if cpu_baseline and readings.cpu and readings.cpu > cpu_baseline * _ABOVE_AVERAGE_FACTOR:
        delta = round(readings.cpu - cpu_baseline)
        if delta >= _ABOVE_AVERAGE_MIN_POINTS:
            return Headline("cpu_above_average", {"delta": delta})
    return Headline("within_expected")


def installed_services(inventory: Iterable[dict]) -> list[dict]:
    """Keep daemons the agent can vouch for: installed, and running or failed.

    The agent reports a stopped service and a client-only install (psql with no
    PostgreSQL server) the same way, as "inactive", so neither is listed.
    """
    return [
        {"name": entry["name"], "ok": entry.get("status") == "active"}
        for entry in inventory
        if entry.get("version", "not found") != "not found"
        and entry.get("status") in ("active", "failed")
    ]
