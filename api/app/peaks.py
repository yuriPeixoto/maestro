"""How close CPU and memory get to their limits: the daily peak and its headroom.

Average CPU and memory have no trend to forecast (the bench found no model better
than "tomorrow equals today"), so capacity for them is a different question: on the
busiest moment of each day, how far below the critical limit did the server stay?
A day's peak is the highest 5-minute average, the same window the server status
judges CPU on, so a few seconds of spike do not count.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy import stats

from app.config import settings

PEAK_METRICS = ("cpu_usage_percent", "memory_usage_percent")
PEAK_WINDOW_MINUTES = 5

# Headroom below this, on the worst day, puts the metric in "watch".
WATCH_HEADROOM_PCT = 15.0
# The peaks' trend is reported only with this many days...
MIN_TREND_DAYS = 7
# ...and counts as moving when it adds up to this much over 30 days.
TREND_CHANGE_PCT = 5.0
_TREND_SPAN_DAYS = 30

# The window frame cannot be a query parameter in ClickHouse; it is a code constant.
_PEAKS_SQL = """
SELECT metric_name, toDate(minute) AS day, max(rolling) AS peak,
       countIf(rolling >= if(metric_name = 'cpu_usage_percent', {cpu_critical:Float64}, {memory_critical:Float64}))
FROM (
    SELECT metric_name, minute,
           avg(value) OVER (PARTITION BY metric_name ORDER BY minute
                            ROWS BETWEEN %(preceding)d PRECEDING AND CURRENT ROW) AS rolling
    FROM (
        SELECT metric_name, toStartOfMinute(timestamp) AS minute, avg(value) AS value
        FROM metrics
        WHERE server_id = {server_id:String}
          AND metric_name IN {metrics:Array(String)}
          AND timestamp >= toStartOfDay(now()) - INTERVAL {days:UInt32} DAY
        GROUP BY metric_name, minute
    )
)
GROUP BY metric_name, day
ORDER BY metric_name, day
""" % {"preceding": PEAK_WINDOW_MINUTES - 1}


def limits(metric_name: str) -> tuple[float, float]:
    """(attention, critical) in percent: the same limits as the server status."""
    if metric_name == "cpu_usage_percent":
        return settings.health_cpu_attention_percent, settings.health_cpu_critical_percent
    return settings.health_memory_attention_percent, settings.health_memory_critical_percent


@dataclass(frozen=True)
class DailyPeak:
    day: date
    peak: float
    minutes_above_critical: int


@dataclass(frozen=True)
class PeakSummary:
    metric_name: str
    attention_pct: float
    critical_pct: float
    days: list[DailyPeak]
    worst: DailyPeak | None
    headroom_pct: float | None
    minutes_above_critical: int
    trend: str   # "rising" | "stable" | "falling" | "unknown"
    status: str  # "safe" | "watch" | "critical" | "no_data"


def summarize(metric_name: str, days: list[DailyPeak]) -> PeakSummary:
    attention, critical = limits(metric_name)
    if not days:
        return PeakSummary(metric_name, attention, critical, [], None, None, 0, "unknown", "no_data")
    worst = max(days, key=lambda d: d.peak)
    headroom = critical - worst.peak
    if headroom <= 0:
        status = "critical"
    elif headroom < WATCH_HEADROOM_PCT:
        status = "watch"
    else:
        status = "safe"
    return PeakSummary(
        metric_name=metric_name,
        attention_pct=attention,
        critical_pct=critical,
        days=days,
        worst=worst,
        headroom_pct=round(headroom, 1),
        minutes_above_critical=sum(d.minutes_above_critical for d in days),
        trend=_trend([d.peak for d in days]),
        status=status,
    )


def _trend(peaks: list[float]) -> str:
    if len(peaks) < MIN_TREND_DAYS:
        return "unknown"
    slope, _, _, _ = stats.theilslopes(np.array(peaks), np.arange(len(peaks)))
    change = slope * _TREND_SPAN_DAYS
    if change >= TREND_CHANGE_PCT:
        return "rising"
    if change <= -TREND_CHANGE_PCT:
        return "falling"
    return "stable"


async def daily_peaks(client, server_id: str, days: int) -> list[PeakSummary]:
    _, cpu_critical = limits("cpu_usage_percent")
    _, memory_critical = limits("memory_usage_percent")
    result = await client.query(_PEAKS_SQL, parameters={
        "server_id": server_id,
        "metrics": list(PEAK_METRICS),
        "days": days,
        "cpu_critical": cpu_critical,
        "memory_critical": memory_critical,
    })
    by_metric: dict[str, list[DailyPeak]] = {m: [] for m in PEAK_METRICS}
    for metric_name, day, peak, above in result.result_rows:
        by_metric[metric_name].append(DailyPeak(day, round(float(peak), 1), int(above)))
    return [summarize(metric, peaks) for metric, peaks in by_metric.items()]
