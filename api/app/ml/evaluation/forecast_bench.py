"""Backtest of capacity forecasts: predict from the past, compare with what happened.

Rolling origin: for every day with enough history, each model is fitted on the
daily averages up to that day and forecasts the next `horizon` days. The error is
the mean absolute difference from the real daily averages, per horizon.

"Last value" (tomorrow equals today) is the yardstick: a model that cannot beat it
is not worth its cost. Prophet, which Maestro used until 2026-11, is compared when
it is installed (`uv pip install prophet`); it is no longer a dependency.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd
from scipy import stats

from app.ml.forecaster import trend_since_shift

MIN_TRAINING_DAYS = 10
HORIZON_DAYS = 7

Model = Callable[[pd.Series, int], np.ndarray]


def last_value(history: pd.Series, horizon: int) -> np.ndarray:
    return np.full(horizon, history.iloc[-1])


def linear(history: pd.Series, horizon: int) -> np.ndarray:
    """Ordinary least squares over the whole history."""
    x = np.arange(len(history))
    slope, intercept = np.polyfit(x, history.to_numpy(), 1)
    return intercept + slope * np.arange(len(history), len(history) + horizon)


def theil_sen(history: pd.Series, horizon: int) -> np.ndarray:
    """Median of pairwise slopes over the whole history."""
    x = np.arange(len(history))
    slope, intercept, _, _ = stats.theilslopes(history.to_numpy(), x)
    return intercept + slope * np.arange(len(history), len(history) + horizon)


def theil_sen_since_shift(history: pd.Series, horizon: int) -> np.ndarray:
    """What production runs (app.ml.forecaster)."""
    return trend_since_shift(history.to_numpy(dtype=float), horizon)[0]


def prophet(history: pd.Series, horizon: int) -> np.ndarray:
    from prophet import Prophet

    frame = pd.DataFrame({"ds": history.index.tz_localize(None) if history.index.tz else history.index,
                          "y": history.to_numpy()})
    model = Prophet(daily_seasonality=False, weekly_seasonality=len(history) >= 14,
                    yearly_seasonality=False, uncertainty_samples=200, changepoint_prior_scale=0.05)
    model.fit(frame)
    future = model.make_future_dataframe(periods=horizon)
    return model.predict(future)["yhat"].to_numpy()[-horizon:]


def _prophet_installed() -> bool:
    try:
        import prophet  # noqa: F401
    except ImportError:
        return False
    return True


MODELS: dict[str, Model] = {
    "last value": last_value,
    "linear (OLS)": linear,
    "Theil-Sen": theil_sen,
    "Theil-Sen since last shift": theil_sen_since_shift,
    **({"Prophet": prophet} if _prophet_installed() else {}),
}

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
