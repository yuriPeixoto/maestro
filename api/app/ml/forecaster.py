"""Capacity forecasting: where a daily series is heading, and when it reaches a limit.

The trend is a Theil-Sen line (the median of pairwise slopes: one odd day barely
moves it) fitted on the stretch after the last level shift. Disk usage moves in
steps (a cleanup, an upgrade, a new log directory): a line through the whole
history would average old levels into the trend.

Chosen with the evaluation bench (app.ml.evaluation, `forecast`): on the first real
server it had the lowest 7-day error for disk usage, below OLS and well below
Prophet, which was removed.

Forecast granularity: daily. Primary use: "disk full in N days".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)

MIN_TRAINING_DAYS = 7
WEEKLY_PATTERN_DAYS = 14
TRAINING_WINDOW_DAYS = 60
FORECAST_HORIZON_DAYS = 14

# A day-to-day change this many robust spreads away from the usual one is a level shift.
SHIFT_SPREADS = 5.0
# Floor for the spread of smooth series, as a share of the mean absolute daily change.
SHIFT_SPREAD_FLOOR = 0.25
# The trend needs a few points after a shift; with fewer, the last level holds.
MIN_TREND_POINTS = 3
# Band around the trend: ± this many robust spreads of the residuals (about 95%).
BAND_SPREADS = 2.0
_MAD_TO_STD = 1.4826


@dataclass
class ForecastPoint:
    date: str          # "YYYY-MM-DD"
    yhat: float
    yhat_lower: float
    yhat_upper: float


@dataclass
class ForecastResult:
    server_id: str
    metric_name: str
    status: str        # "ok" | "insufficient_data" | "error"
    horizon_days: int
    trained_at: str    # ISO-8601 UTC
    points: list[ForecastPoint]
    trend_per_day: float | None = None    # slope of the trend, in the metric's unit per day
    level_shift_on: str | None = None     # "YYYY-MM-DD" of the last level shift, if any


def forecast_maturity(days_collected: int) -> str:
    """Name the stage of the forecast for a number of collected days."""
    if days_collected < MIN_TRAINING_DAYS:
        return "learning"
    if days_collected < WEEKLY_PATTERN_DAYS:
        return "preliminary"
    if days_collected < TRAINING_WINDOW_DAYS:
        return "evolving"
    return "complete"


def last_level_shift(values: np.ndarray) -> int:
    """Index where the series last jumped to a new level, or 0."""
    steps = np.diff(values)
    if len(steps) < 3:
        return 0
    center = np.median(steps)
    spread = max(np.median(np.abs(steps - center)) * _MAD_TO_STD, np.mean(np.abs(steps)) * SHIFT_SPREAD_FLOOR)
    if spread == 0:
        return 0
    jumps = np.flatnonzero(np.abs(steps - center) > SHIFT_SPREADS * spread)
    return int(jumps[-1]) + 1 if len(jumps) else 0


@dataclass(frozen=True)
class Trend:
    since: int        # index of the first point after the last level shift (0 when none)
    slope: float      # per step (per day for daily series)
    intercept: float  # value at `since`
    band: float       # half-width of the likely range


def fit_trend(values: np.ndarray) -> Trend:
    """Theil-Sen line on the stretch after the last level shift; flat at the last value when too short."""
    since = last_level_shift(values)
    recent = values[since:]
    if len(recent) < MIN_TREND_POINTS:
        return Trend(since, 0.0, float(values[-1]), 0.0)
    x = np.arange(len(recent))
    slope, intercept, _, _ = stats.theilslopes(recent, x)
    residuals = recent - (intercept + slope * x)
    band = BAND_SPREADS * float(np.median(np.abs(residuals - np.median(residuals))) * _MAD_TO_STD)
    return Trend(since, float(slope), float(intercept), band)


def trend_since_shift(values: np.ndarray, horizon: int) -> tuple[np.ndarray, float]:
    """Forecast `horizon` steps ahead and the band half-width, from the stretch after the last shift."""
    trend = fit_trend(values)
    future = np.arange(len(values) - trend.since, len(values) - trend.since + horizon)
    return trend.intercept + trend.slope * future, trend.band


def forecast(
    server_id: str,
    metric_name: str,
    daily_data: list[dict],
    horizon_days: int = FORECAST_HORIZON_DAYS,
    trained_at: str = "",
) -> ForecastResult:
    """Forecast from daily_data: list of {"date": "YYYY-MM-DD", "avg_value": float}."""
    if len(daily_data) < MIN_TRAINING_DAYS:
        return ForecastResult(server_id, metric_name, "insufficient_data", horizon_days, trained_at, [])
    try:
        values = np.array([d["avg_value"] for d in daily_data], dtype=float)
        trend = fit_trend(values)
        yhat, band = trend_since_shift(values, horizon_days)
        last_date = date.fromisoformat(daily_data[-1]["date"])
        points = [
            ForecastPoint(
                date=str(last_date + timedelta(days=i + 1)),
                yhat=float(y),
                yhat_lower=float(y - band),
                yhat_upper=float(y + band),
            )
            for i, y in enumerate(yhat)
        ]
        shift_on = daily_data[trend.since]["date"] if trend.since > 0 else None
        return ForecastResult(server_id, metric_name, "ok", horizon_days, trained_at, points,
                              trend_per_day=trend.slope, level_shift_on=shift_on)
    except Exception as exc:
        logger.error("forecaster: failed for %s/%s: %s", server_id, metric_name, exc)
        return ForecastResult(server_id, metric_name, "error", horizon_days, trained_at, [])


def compute_runway(points: list[ForecastPoint], threshold: float = 90.0) -> int | None:
    """Days from today until yhat first crosses threshold. None if it never does in the horizon."""
    for i, p in enumerate(points):
        if p.yhat >= threshold:
            return i + 1
    return None
