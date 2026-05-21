"""Capacity forecasting for Maestro — issue #27.

Uses Prophet (Facebook/Meta) for trend + seasonality decomposition when available,
with a fallback to sklearn LinearRegression when Prophet cannot be imported
(e.g. missing CmdStan on the host). Both produce the same output schema.

Forecast granularity: daily.
Primary use case: "disk full in X days", "memory runway at current growth".
NOT suitable for real-time anomaly detection (see ADR-005).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    from prophet import Prophet as _Prophet
    _PROPHET_AVAILABLE = True
except Exception:
    _PROPHET_AVAILABLE = False
    logger.warning("forecaster: prophet not available — falling back to LinearRegression")

_MIN_TRAINING_DAYS = 7


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


def _days_to_threshold(points: list[ForecastPoint], threshold: float) -> int | None:
    """Return how many days until yhat first reaches threshold, or None if never."""
    for i, p in enumerate(points):
        if p.yhat >= threshold:
            return i
    return None


def forecast(
    server_id: str,
    metric_name: str,
    daily_data: list[dict],
    horizon_days: int = 14,
    trained_at: str = "",
) -> ForecastResult:
    """Train a model on daily_data and return a ForecastResult.

    daily_data: list of {"date": "YYYY-MM-DD", "avg_value": float}
    """
    if len(daily_data) < _MIN_TRAINING_DAYS:
        return ForecastResult(
            server_id=server_id,
            metric_name=metric_name,
            status="insufficient_data",
            horizon_days=horizon_days,
            trained_at=trained_at,
            points=[],
        )

    try:
        if _PROPHET_AVAILABLE:
            points = _forecast_prophet(daily_data, horizon_days)
        else:
            points = _forecast_linear(daily_data, horizon_days)

        return ForecastResult(
            server_id=server_id,
            metric_name=metric_name,
            status="ok",
            horizon_days=horizon_days,
            trained_at=trained_at,
            points=points,
        )
    except Exception as exc:
        logger.error("forecaster: failed for %s/%s: %s", server_id, metric_name, exc)
        return ForecastResult(
            server_id=server_id,
            metric_name=metric_name,
            status="error",
            horizon_days=horizon_days,
            trained_at=trained_at,
            points=[],
        )


def _forecast_prophet(daily_data: list[dict], horizon_days: int) -> list[ForecastPoint]:
    df = pd.DataFrame({"ds": [d["date"] for d in daily_data],
                        "y":  [d["avg_value"] for d in daily_data]})
    df["ds"] = pd.to_datetime(df["ds"])

    model = _Prophet(
        daily_seasonality=False,
        weekly_seasonality=(len(daily_data) >= 14),
        yearly_seasonality=False,
        uncertainty_samples=200,
        changepoint_prior_scale=0.05,
    )
    model.fit(df)

    future = model.make_future_dataframe(periods=horizon_days)
    fc = model.predict(future)

    # Return only the future window (beyond the last training date)
    last_train = df["ds"].max()
    future_fc = fc[fc["ds"] > last_train].head(horizon_days)

    return [
        ForecastPoint(
            date=str(row["ds"].date()),
            yhat=float(row["yhat"]),
            yhat_lower=float(row["yhat_lower"]),
            yhat_upper=float(row["yhat_upper"]),
        )
        for _, row in future_fc.iterrows()
    ]


def _forecast_linear(daily_data: list[dict], horizon_days: int) -> list[ForecastPoint]:
    """Fallback: OLS linear regression with prediction interval via residual std."""
    from sklearn.linear_model import LinearRegression

    xs = np.arange(len(daily_data)).reshape(-1, 1)
    ys = np.array([d["avg_value"] for d in daily_data])

    model = LinearRegression()
    model.fit(xs, ys)

    # Residual std for approximate prediction interval (95% ≈ ±2σ)
    residuals = ys - model.predict(xs)
    sigma = float(np.std(residuals)) * 2.0

    last_date = date.fromisoformat(daily_data[-1]["date"])
    points: list[ForecastPoint] = []
    for i in range(1, horizon_days + 1):
        x_new = np.array([[len(daily_data) + i - 1]])
        yhat = float(model.predict(x_new)[0])
        points.append(ForecastPoint(
            date=str(last_date + timedelta(days=i)),
            yhat=yhat,
            yhat_lower=yhat - sigma,
            yhat_upper=yhat + sigma,
        ))
    return points


def compute_runway(points: list[ForecastPoint], threshold: float = 90.0) -> int | None:
    """Days until yhat first crosses threshold. None if it never does in the horizon."""
    return _days_to_threshold(points, threshold)
