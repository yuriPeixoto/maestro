"""
The CPU-heavy ML functions must run in the child process: arguments and results
cross a process boundary, so everything sent there has to pickle.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.ml import pool
from app.ml.forecaster import forecast
from app.ml.seasonal import SeasonalBaseline


@pytest.fixture(autouse=True)
def _fresh_pool():
    yield
    pool.shutdown()


def _history(days: int = 3) -> pd.DataFrame:
    index = pd.date_range("2026-11-01", periods=days * 1440, freq="1min", tz="UTC", name="minute")
    rng = np.random.default_rng(42)
    return pd.DataFrame({
        "cpu_usage_percent": 10 + rng.normal(0, 1, len(index)),
        "disk_write_bytes_per_sec": 2e5 * np.exp(rng.normal(0, 0.2, len(index))),
    }, index=index)


@pytest.mark.asyncio
async def test_the_seasonal_baseline_is_fitted_in_the_child_process():
    history = _history()

    baseline = await pool.run_in_ml_process(SeasonalBaseline.fit, history)

    assert baseline.metrics == ["cpu_usage_percent", "disk_write_bytes_per_sec"]
    assert not baseline.flag(history.iloc[:60]).any()


@pytest.mark.asyncio
async def test_forecast_runs_in_the_child_process():
    daily = [{"date": f"2026-10-{d:02d}", "avg_value": 40 + d * 0.1} for d in range(1, 21)]

    result = await pool.run_in_ml_process(
        forecast, server_id="web-1", metric_name="disk_usage_percent", daily_data=daily, horizon_days=3,
    )

    assert result.status == "ok"
    assert len(result.points) == 3
