"""
The CPU-heavy ML functions must run in the child process: arguments and results
cross a process boundary, so everything sent there has to pickle.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.feature_engineering import compute_features
from app.ml import pool
from app.ml.anomaly_detector import FEATURE_COLUMNS, train_and_score
from app.ml.forecaster import forecast


@pytest.fixture(autouse=True)
def _fresh_pool():
    yield
    pool.shutdown()


def _raw_series(points: int = 600) -> pd.DataFrame:
    start = datetime(2026, 11, 2, tzinfo=timezone.utc)
    rng = np.random.default_rng(42)
    return pd.DataFrame({
        "timestamp": [start + timedelta(seconds=5 * i) for i in range(points)],
        "value": 10 + rng.normal(0, 1, points),
    })


@pytest.mark.asyncio
async def test_features_and_training_run_in_the_child_process():
    features = await pool.run_in_ml_process(compute_features, _raw_series())
    assert set(FEATURE_COLUMNS) <= set(features.columns)

    model, metadata, scores = await pool.run_in_ml_process(train_and_score, features, "web-1", "cpu", 0.05)

    assert metadata.n_samples == len(features)
    assert len(scores) == len(features)
    assert 0.0 <= scores.min() and scores.max() <= 1.0
    assert model.decision_function(features[FEATURE_COLUMNS].values).shape == (len(features),)


@pytest.mark.asyncio
async def test_forecast_runs_in_the_child_process():
    daily = [{"date": f"2026-10-{d:02d}", "avg_value": 40 + d * 0.1} for d in range(1, 21)]

    result = await pool.run_in_ml_process(
        forecast, server_id="web-1", metric_name="disk_usage_percent", daily_data=daily, horizon_days=3,
    )

    assert result.status == "ok"
    assert len(result.points) == 3
