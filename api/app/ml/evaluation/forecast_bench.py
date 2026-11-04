"""Backtest of capacity forecasts: predict from the past, compare with what happened.

Rolling origin: for every day with enough history, each model is fitted on the
daily averages up to that day and forecasts the next `horizon` days. The error is
the mean absolute difference from the real daily averages, per horizon.

"Last value" (tomorrow equals today) is the yardstick: a model that cannot beat it
is not worth its cost.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd
from scipy import stats

from app.ml.forecaster import _forecast_linear, _forecast_prophet

MIN_TRAINING_DAYS = 10
HORIZON_DAYS = 7
# A day-to-day change this many robust spreads above the usual one is a level shift.
SHIFT_SPREADS = 5.0
SHIFT_SPREAD_FLOOR = 0.25

Model = Callable[[pd.Series, int], np.ndarray]


def last_value(history: pd.Series, horizon: int) -> np.ndarray:
    return np.full(horizon, history.iloc[-1])


def linear(history: pd.Series, horizon: int) -> np.ndarray:
    return np.array([p.yhat for p in _forecast_linear(_as_daily(history), horizon)])


def prophet(history: pd.Series, horizon: int) -> np.ndarray:
    return np.array([p.yhat for p in _forecast_prophet(_as_daily(history), horizon)])


def theil_sen(history: pd.Series, horizon: int) -> np.ndarray:
    """Median of pairwise slopes: one odd day barely moves the trend."""
    x = np.arange(len(history))
    slope, intercept, _, _ = stats.theilslopes(history.to_numpy(), x)
    future = np.arange(len(history), len(history) + horizon)
    return intercept + slope * future


def theil_sen_since_shift(history: pd.Series, horizon: int) -> np.ndarray:
    """Theil-Sen on the stretch after the last level shift (a cleanup, an upgrade)."""
    start = last_level_shift(history)
    recent = history.iloc[start:]
    if len(recent) < 3:
        return last_value(history, horizon)
    return theil_sen(recent, horizon)


def last_level_shift(history: pd.Series) -> int:
    """Position where the series last jumped to a new level, or 0."""
    steps = history.diff().dropna()
    if len(steps) < 3:
        return 0
    center = steps.median()
    # Floor for smooth series, whose MAD of steps is close to zero.
    spread = max((steps - center).abs().median() * 1.4826, steps.abs().mean() * SHIFT_SPREAD_FLOOR)
    if spread == 0:
        return 0
    jumps = np.flatnonzero(np.abs(steps.to_numpy() - center) > SHIFT_SPREADS * spread)
    return int(jumps[-1]) + 1 if len(jumps) else 0


MODELS: dict[str, Model] = {
    "last value": last_value,
    "linear (OLS)": linear,
    "Theil-Sen": theil_sen,
    "Theil-Sen since last shift": theil_sen_since_shift,
    "Prophet": prophet,
}


def _as_daily(history: pd.Series) -> list[dict]:
    return [{"date": day.strftime("%Y-%m-%d"), "avg_value": float(v)} for day, v in history.items()]


def daily_means(frame: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    """Daily averages, keeping only days with at least 90% of their minutes."""
    coverage = frame[metrics].notna().groupby(frame.index.normalize()).mean()
    means = frame[metrics].groupby(frame.index.normalize()).mean()
    return means.where(coverage >= 0.9).dropna(how="all")


def backtest(series: pd.Series, horizon: int = HORIZON_DAYS) -> pd.DataFrame:
    """Mean absolute error per model (rows) and horizon in days (columns)."""
    series = series.dropna()
    errors: dict[str, list[np.ndarray]] = {name: [] for name in MODELS}
    for end in range(MIN_TRAINING_DAYS, len(series) - horizon + 1):
        history, actual = series.iloc[:end], series.iloc[end:end + horizon].to_numpy()
        for name, model in MODELS.items():
            errors[name].append(np.abs(model(history, horizon) - actual))
    return pd.DataFrame(
        {name: np.mean(np.vstack(errs), axis=0) for name, errs in errors.items() if errs},
        index=range(1, horizon + 1),
    ).T


def render(frame: pd.DataFrame, metrics: list[str], label: str) -> str:
    daily = daily_means(frame, metrics)
    lines = [f"# Capacity forecast backtest: {label}", "",
             f"{len(daily)} complete days, {daily.index[0]:%Y-%m-%d} to {daily.index[-1]:%Y-%m-%d}. "
             f"Every origin with at least {MIN_TRAINING_DAYS} days of history forecasts {HORIZON_DAYS} days; "
             "the tables show the mean absolute error, in the metric's unit, 1, 3 and 7 days ahead.", ""]
    for metric in metrics:
        table = backtest(daily[metric])
        if table.empty:
            continue
        origins = len(daily[metric].dropna()) - MIN_TRAINING_DAYS - HORIZON_DAYS + 1
        lines += [f"## {metric} ({origins} origins)", "",
                  "| Model | 1 day | 3 days | 7 days |", "|---|---|---|---|"]
        for name, row in table.sort_values(HORIZON_DAYS).iterrows():
            lines.append(f"| {name} | {row[1]:.2f} | {row[3]:.2f} | {row[HORIZON_DAYS]:.2f} |")
        lines.append("")
    return "\n".join(lines)
