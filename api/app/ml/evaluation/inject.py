"""Synthetic anomalies written into a copy of real data, with their labels.

Real data has no labels: nobody marked which minutes were incidents. So the bench
takes a clean stretch of real metrics, plants anomalies whose time and shape are
known, and checks what each detector finds. Sizes are relative to each metric's
own spread (robust standard deviation), so "4 spreads" means the same kind of
surprise for CPU percent and for disk bytes per second.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

_MAD_TO_STD = 1.4826
_PERCENT_SUFFIX = "_percent"
_MIN_SEPARATION = pd.Timedelta(hours=2)
_QUIET_HOURS = 6  # the hours of the day with the lowest CPU, for the off-hours case


@dataclass(frozen=True)
class InjectedEvent:
    kind: str
    metrics: tuple[str, ...]
    start: pd.Timestamp
    end: pd.Timestamp  # exclusive
    size: str  # human-readable magnitude, for the report


@dataclass(frozen=True)
class Scenario:
    """One kind of anomaly: its duration, the metrics it touches and how it bends them."""
    kind: str
    minutes: int
    metrics: tuple[str, ...]
    description: str
    count: int = 5
    extra: dict = field(default_factory=dict)


def metric_spread(frame: pd.DataFrame) -> pd.Series:
    """Robust spread per metric: 1.4826 × MAD, falling back to the standard deviation."""
    median = frame.median()
    mad = (frame - median).abs().median() * _MAD_TO_STD
    return mad.where(mad > 0, frame.std()).fillna(0.0)


def scenarios() -> list[Scenario]:
    return [
        Scenario("spike", 5, ("cpu_usage_percent", "disk_write_bytes_per_sec", "process_count"),
                 "one metric jumps for 5 minutes"),
        Scenario("level_shift", 60, ("memory_usage_percent", "cpu_usage_percent", "process_count"),
                 "one metric moves to a new level for an hour"),
        Scenario("slow_ramp", 420, ("memory_usage_percent",),
                 "memory climbs linearly for 6 hours, then holds for 1 (a leak)", count=3),
        Scenario("off_hours", 60, ("cpu_usage_percent", "memory_usage_percent"),
                 "business-hours load in the quietest hours of the night"),
        Scenario("joint", 30, ("disk_write_bytes_per_sec", "process_count"),
                 "two metrics move together, each by a modest amount", extra={"spreads": 2.5}),
    ]


def inject(
    test: pd.DataFrame,
    train: pd.DataFrame,
    spreads: float,
    seed: int = 7,
) -> tuple[pd.DataFrame, list[InjectedEvent]]:
    """Return a copy of `test` with anomalies planted, and the list of what was planted.

    `spreads` sets the size of spikes, level shifts and ramps; off-hours and joint
    anomalies use their own sizes, described in each event.
    """
    rng = np.random.default_rng(seed)
    data = test.copy()
    spread = metric_spread(train)
    quiet_hours = _quiet_hours(train)
    busy_level = _busy_level(train)
    occupied: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    events: list[InjectedEvent] = []

    for scenario in scenarios():
        for i in range(scenario.count):
            metrics = (scenario.metrics[i % len(scenario.metrics)],) if scenario.kind in ("spike", "level_shift") \
                else scenario.metrics
            hours = quiet_hours if scenario.kind == "off_hours" else None
            start = _free_start(data, scenario.minutes, occupied, rng, metrics, hours)
            if start is None:
                continue
            end = start + pd.Timedelta(minutes=scenario.minutes)
            occupied.append((start, end))
            window = data.index[(data.index >= start) & (data.index < end)]
            size = _apply(data, window, scenario, metrics, spread, spreads, busy_level)
            events.append(InjectedEvent(scenario.kind, metrics, start, end, size))

    for metric in data.columns:
        if metric.endswith(_PERCENT_SUFFIX):
            data[metric] = data[metric].clip(0, 100)
        else:
            data[metric] = data[metric].clip(lower=0)
    events.sort(key=lambda event: event.start)
    return data, events


def _apply(data, window, scenario: Scenario, metrics, spread, spreads: float, busy_level) -> str:
    if scenario.kind == "spike" or scenario.kind == "level_shift":
        metric = metrics[0]
        data.loc[window, metric] += spreads * spread[metric]
        return f"+{spreads:g} spreads"
    if scenario.kind == "slow_ramp":
        metric = metrics[0]
        ramp_minutes = scenario.minutes - 60
        ramp = np.minimum(np.arange(len(window)) / ramp_minutes, 1.0) * spreads * spread[metric]
        data.loc[window, metric] += ramp
        return f"ramp to +{spreads:g} spreads"
    if scenario.kind == "off_hours":
        for metric in metrics:
            data.loc[window, metric] = np.maximum(data.loc[window, metric], busy_level[metric])
        return "busiest-hour level"
    joint = scenario.extra["spreads"]
    for metric in metrics:
        data.loc[window, metric] += joint * spread[metric]
    return f"+{joint:g} spreads each"


def _free_start(data, minutes: int, occupied, rng, metrics, hours) -> pd.Timestamp | None:
    """A random start whose window has data and stays clear of the other events."""
    length = pd.Timedelta(minutes=minutes)
    candidates = data.index[: len(data.index) - minutes]
    if hours is not None:
        candidates = candidates[candidates.hour.isin(hours)]
    for _ in range(200):
        start = candidates[rng.integers(len(candidates))]
        end = start + length
        if any(start < o_end + _MIN_SEPARATION and o_start < end + _MIN_SEPARATION for o_start, o_end in occupied):
            continue
        window = data.loc[start:end - pd.Timedelta(minutes=1), list(metrics)]
        if window.notna().all().all():
            return start
    return None


def _quiet_hours(train: pd.DataFrame) -> list[int]:
    by_hour = train["cpu_usage_percent"].groupby(train.index.hour).median()
    return list(by_hour.nsmallest(_QUIET_HOURS).index)


def _busy_level(train: pd.DataFrame) -> pd.Series:
    """Per metric, the median of the busiest hour of the day."""
    by_hour = train.groupby(train.index.hour).median()
    busiest = by_hour["cpu_usage_percent"].idxmax()
    return by_hour.loc[busiest]
