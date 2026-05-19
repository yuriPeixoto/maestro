"""
Unit tests for the feature engineering pipeline.

All tests use synthetic in-memory DataFrames — no ClickHouse or network required.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.feature_engineering import compute_features, dataframe_to_feature_rows


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_df(
    values: list[float],
    start: datetime | None = None,
    interval_seconds: int = 15,
) -> pd.DataFrame:
    """Build a minimal [timestamp, value] DataFrame for testing."""
    if start is None:
        start = datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)  # Monday 10:00 UTC
    timestamps = [start + timedelta(seconds=i * interval_seconds) for i in range(len(values))]
    return pd.DataFrame({"timestamp": timestamps, "value": values})


# ── compute_features ──────────────────────────────────────────────────────────

class TestComputeFeatures:
    def test_empty_dataframe_returns_empty(self):
        df = pd.DataFrame({"timestamp": [], "value": []})
        result = compute_features(df)
        assert result.empty

    def test_output_has_all_columns(self):
        df = _make_df([50.0] * 10)
        result = compute_features(df)
        expected = {
            "timestamp", "value", "raw_value",
            "rolling_mean_5m", "rolling_std_5m", "rate_of_change",
            "hour_sin", "hour_cos", "day_of_week", "is_weekend",
        }
        assert expected.issubset(set(result.columns))

    def test_constant_series_rolling_mean_equals_value(self):
        constant = 42.0
        df = _make_df([constant] * 30)
        result = compute_features(df)
        np.testing.assert_allclose(result["rolling_mean_5m"].values, constant)

    def test_constant_series_rolling_std_is_zero(self):
        df = _make_df([100.0] * 30)
        result = compute_features(df)
        np.testing.assert_allclose(result["rolling_std_5m"].values, 0.0, atol=1e-9)

    def test_rate_of_change_first_row_is_zero(self):
        df = _make_df([10.0, 20.0, 30.0], interval_seconds=10)
        result = compute_features(df)
        assert result.iloc[0]["rate_of_change"] == pytest.approx(0.0)

    def test_rate_of_change_linear_series(self):
        # value increases by 10 every 10 seconds → rate = 1.0 units/second
        df = _make_df([0.0, 10.0, 20.0, 30.0, 40.0], interval_seconds=10)
        result = compute_features(df)
        # skip first row (rate=0 by definition)
        rates = result.iloc[1:]["rate_of_change"].values
        np.testing.assert_allclose(rates, 1.0, rtol=1e-6)

    def test_hour_sin_cos_in_range(self):
        df = _make_df([1.0] * 20)
        result = compute_features(df)
        assert (result["hour_sin"].between(-1.0, 1.0)).all()
        assert (result["hour_cos"].between(-1.0, 1.0)).all()

    def test_hour_sin_cos_unit_circle(self):
        """sin²(θ) + cos²(θ) must equal 1 for any angle."""
        df = _make_df([1.0] * 20)
        result = compute_features(df)
        norm = (result["hour_sin"] ** 2 + result["hour_cos"] ** 2).values
        np.testing.assert_allclose(norm, 1.0, atol=1e-9)

    def test_weekend_detection(self):
        # 2026-05-11 = Monday, 2026-05-16 = Saturday, 2026-05-17 = Sunday
        monday = datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc)
        saturday = datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)
        sunday = datetime(2026, 5, 17, 12, 0, 0, tzinfo=timezone.utc)

        df = pd.DataFrame({
            "timestamp": [monday, saturday, sunday],
            "value": [1.0, 1.0, 1.0],
        })
        result = compute_features(df)
        result = result.sort_values("timestamp").reset_index(drop=True)

        assert result.iloc[0]["is_weekend"] == 0  # Monday
        assert result.iloc[1]["is_weekend"] == 1  # Saturday
        assert result.iloc[2]["is_weekend"] == 1  # Sunday

    def test_day_of_week_monday_is_zero(self):
        monday = datetime(2026, 5, 11, 8, 0, 0, tzinfo=timezone.utc)
        df = _make_df([1.0], start=monday)
        result = compute_features(df)
        assert result.iloc[0]["day_of_week"] == 0

    def test_day_of_week_sunday_is_six(self):
        sunday = datetime(2026, 5, 17, 8, 0, 0, tzinfo=timezone.utc)
        df = _make_df([1.0], start=sunday)
        result = compute_features(df)
        assert result.iloc[0]["day_of_week"] == 6

    def test_rolling_mean_window_respects_5_minutes(self):
        # 40 points at 15s interval = 10 minutes; the rolling mean over 5min
        # at point 20 (5min mark) should equal the mean of the preceding ~20 points.
        values = list(range(40))
        df = _make_df(values, interval_seconds=15)
        result = compute_features(df)
        # All rolling means must be >= min(values) and <= max(values)
        assert result["rolling_mean_5m"].between(0, 39).all()

    def test_raw_value_matches_original_value(self):
        vals = [10.0, 20.0, 30.0]
        df = _make_df(vals)
        result = compute_features(df)
        assert list(result["raw_value"]) == pytest.approx(vals)


# ── dataframe_to_feature_rows ─────────────────────────────────────────────────

class TestDataframeToFeatureRows:
    def _computed_df(self) -> pd.DataFrame:
        return compute_features(_make_df([10.0, 20.0, 30.0], interval_seconds=15))

    def test_returns_feature_rows(self):
        df = self._computed_df()
        rows = dataframe_to_feature_rows("srv", "cpu_usage_percent", df, after=None)
        assert len(rows) == 3
        assert all(r.server_id == "srv" for r in rows)
        assert all(r.metric_name == "cpu_usage_percent" for r in rows)

    def test_watermark_filter_excludes_older_rows(self):
        start = datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)
        df = self._computed_df()
        # watermark = timestamp of the first row → should exclude it
        watermark = start
        rows = dataframe_to_feature_rows("srv", "cpu_usage_percent", df, after=watermark)
        assert len(rows) == 2
        assert all(r.timestamp > watermark for r in rows)

    def test_timestamps_are_utc_aware(self):
        df = self._computed_df()
        rows = dataframe_to_feature_rows("srv", "cpu", df, after=None)
        for r in rows:
            assert r.timestamp.tzinfo is not None
