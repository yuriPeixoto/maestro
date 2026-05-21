"""
Unit tests for Isolation Forest training, scoring, and model persistence.
No ClickHouse or network required — all I/O is mocked or uses tmp_path.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import IsolationForest

from app.ml.anomaly_detector import (
    FEATURE_COLUMNS,
    score_dataframe,
    train_model,
)
from app.ml.model_store import ModelMetadata, ModelStore


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _synthetic_features(n: int = 600, seed: int = 0) -> pd.DataFrame:
    """
    Generate n rows of synthetic feature data representing normal server behaviour.
    Timestamps are 15s apart starting from a fixed Monday 10:00 UTC.
    """
    rng = np.random.default_rng(seed)
    start = datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)
    timestamps = [start + timedelta(seconds=i * 15) for i in range(n)]

    hour_frac = np.array([t.hour + t.minute / 60 for t in timestamps])
    radians = 2 * math.pi * hour_frac / 24

    df = pd.DataFrame({
        "timestamp": timestamps,
        "raw_value": rng.normal(50.0, 5.0, n),
        "rolling_mean_5m": rng.normal(50.0, 3.0, n),
        "rolling_std_5m": rng.uniform(0.5, 3.0, n),
        "rate_of_change": rng.normal(0.0, 0.1, n),
        "hour_sin": np.sin(radians),
        "hour_cos": np.cos(radians),
        "day_of_week": np.array([t.weekday() for t in timestamps], dtype=np.uint8),
        "is_weekend": np.array([int(t.weekday() >= 5) for t in timestamps], dtype=np.uint8),
    })
    return df


# ── train_model ───────────────────────────────────────────────────────────────

class TestTrainModel:
    def test_returns_fitted_model_and_metadata(self):
        df = _synthetic_features(600)
        model, meta = train_model(df, "srv", "cpu_usage_percent", contamination=0.05)
        assert isinstance(model, IsolationForest)
        assert isinstance(meta, ModelMetadata)

    def test_metadata_fields_present(self):
        df = _synthetic_features(600)
        _, meta = train_model(df, "srv", "cpu_usage_percent", contamination=0.05)
        assert meta.server_id == "srv"
        assert meta.metric_name == "cpu_usage_percent"
        assert meta.n_samples == 600
        assert meta.contamination == pytest.approx(0.05)
        assert meta.trained_at != ""
        assert meta.data_range_start != ""
        assert meta.data_range_end != ""
        assert meta.score_min < meta.score_max  # meaningful normalisation bounds

    def test_model_has_correct_feature_count(self):
        df = _synthetic_features(600)
        model, _ = train_model(df, "srv", "cpu", contamination=0.05)
        assert model.n_features_in_ == len(FEATURE_COLUMNS)

    def test_score_bounds_from_training_set(self):
        df = _synthetic_features(600)
        _, meta = train_model(df, "srv", "cpu", contamination=0.05)
        assert meta.score_min <= meta.score_max


# ── score_dataframe ───────────────────────────────────────────────────────────

class TestScoreDataframe:
    def test_scores_in_unit_range(self):
        df = _synthetic_features(600)
        model, meta = train_model(df, "srv", "cpu", contamination=0.05)
        scores = score_dataframe(model, meta, df)
        assert scores.min() >= 0.0
        assert scores.max() <= 1.0

    def test_output_length_matches_input(self):
        df = _synthetic_features(600)
        model, meta = train_model(df, "srv", "cpu", contamination=0.05)
        scores = score_dataframe(model, meta, df)
        assert len(scores) == len(df)

    def test_anomaly_scores_higher_than_normal(self):
        """Injected spike rows should score higher than normal rows."""
        rng = np.random.default_rng(42)
        normal_df = _synthetic_features(800)
        model, meta = train_model(normal_df, "srv", "cpu", contamination=0.05)

        # Normal test rows
        normal_test = _synthetic_features(50, seed=99)
        normal_scores = score_dataframe(model, meta, normal_test)

        # Anomalous rows: extreme values on all features
        anomaly_df = normal_test.copy()
        for col in ["rolling_mean_5m", "rolling_std_5m", "rate_of_change", "raw_value"]:
            anomaly_df[col] = anomaly_df[col] * 10 + 200
        anomaly_scores = score_dataframe(model, meta, anomaly_df)

        assert anomaly_scores.mean() > normal_scores.mean()


# ── ModelStore ────────────────────────────────────────────────────────────────

class TestModelStore:
    def test_get_returns_none_when_no_model(self, tmp_path):
        store = ModelStore(tmp_path)
        assert store.get("unknown", "cpu_usage_percent") is None

    def test_score_returns_none_without_model(self, tmp_path):
        store = ModelStore(tmp_path)
        features = np.zeros(len(FEATURE_COLUMNS))
        assert store.score("srv", "cpu", features) is None

    def test_save_and_load_roundtrip(self, tmp_path):
        df = _synthetic_features(600)
        model, meta = train_model(df, "srv", "cpu_usage_percent", contamination=0.05)

        store = ModelStore(tmp_path)
        store.save("srv", "cpu_usage_percent", model, meta)

        # Reload from a fresh store instance
        store2 = ModelStore(tmp_path)
        count = store2.load_all()
        assert count == 1
        entry = store2.get("srv", "cpu_usage_percent")
        assert entry is not None
        loaded_model, loaded_meta = entry
        assert loaded_meta.n_samples == 600
        assert loaded_meta.server_id == "srv"

    def test_blue_green_staging_files_removed_after_save(self, tmp_path):
        df = _synthetic_features(600)
        model, meta = train_model(df, "srv", "cpu", contamination=0.05)
        store = ModelStore(tmp_path)
        store.save("srv", "cpu", model, meta)

        # No .new.pkl or .new.json should remain
        staging = list(tmp_path.glob("**/*.new.*"))
        assert staging == []

    def test_final_pkl_exists_after_save(self, tmp_path):
        df = _synthetic_features(600)
        model, meta = train_model(df, "srv", "cpu", contamination=0.05)
        store = ModelStore(tmp_path)
        store.save("srv", "cpu", model, meta)
        assert (tmp_path / "srv" / "cpu.pkl").exists()
        assert (tmp_path / "srv" / "cpu.json").exists()

    def test_metadata_json_is_valid(self, tmp_path):
        df = _synthetic_features(600)
        model, meta = train_model(df, "srv", "cpu", contamination=0.05)
        store = ModelStore(tmp_path)
        store.save("srv", "cpu", model, meta)
        raw = json.loads((tmp_path / "srv" / "cpu.json").read_text())
        for field in ("server_id", "metric_name", "trained_at", "n_samples",
                      "contamination", "score_min", "score_max", "version"):
            assert field in raw

    def test_score_in_unit_range_after_save(self, tmp_path):
        df = _synthetic_features(600)
        model, meta = train_model(df, "srv", "cpu", contamination=0.05)
        store = ModelStore(tmp_path)
        store.save("srv", "cpu", model, meta)

        features = df[FEATURE_COLUMNS].values[0]
        score = store.score("srv", "cpu", features)
        assert score is not None
        assert 0.0 <= score <= 1.0

    def test_load_all_empty_dir(self, tmp_path):
        store = ModelStore(tmp_path)
        assert store.load_all() == 0

    def test_load_all_nonexistent_dir(self, tmp_path):
        store = ModelStore(tmp_path / "does_not_exist")
        assert store.load_all() == 0
