"""Unit tests for the River online anomaly detector."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.ml.river_detector import RiverDetector


def _ts(hour: int = 10) -> datetime:
    return datetime(2026, 5, 12, hour, 0, 0, tzinfo=timezone.utc)


class TestRiverDetector:
    def test_score_in_unit_range(self, tmp_path):
        det = RiverDetector(tmp_path)
        score = det.update_and_score("srv", "cpu", 50.0, _ts())
        assert 0.0 <= score <= 1.0

    def test_score_does_not_raise_on_repeated_calls(self, tmp_path):
        det = RiverDetector(tmp_path)
        for i in range(50):
            score = det.update_and_score("srv", "cpu", float(i % 100), _ts(i % 24))
            assert 0.0 <= score <= 1.0

    def test_separate_models_per_metric(self, tmp_path):
        det = RiverDetector(tmp_path)
        det.update_and_score("srv", "cpu", 50.0, _ts())
        det.update_and_score("srv", "memory", 70.0, _ts())
        assert ("srv", "cpu") in det._models
        assert ("srv", "memory") in det._models

    def test_save_and_load_roundtrip(self, tmp_path):
        det = RiverDetector(tmp_path)
        for i in range(20):
            det.update_and_score("srv", "cpu", float(i), _ts())
        det.save_all()

        # Verify file exists
        assert (tmp_path / "river" / "srv" / "cpu.river.pkl").exists()

        # Load in fresh instance
        det2 = RiverDetector(tmp_path)
        count = det2.load_all()
        assert count == 1

        # Should score without error after reload
        score = det2.update_and_score("srv", "cpu", 50.0, _ts())
        assert 0.0 <= score <= 1.0

    def test_load_all_empty_dir(self, tmp_path):
        det = RiverDetector(tmp_path)
        assert det.load_all() == 0

    def test_anomaly_score_higher_for_extreme_value(self, tmp_path):
        """After training on normal data, an extreme spike should score higher."""
        det = RiverDetector(tmp_path)
        # Train on normal data
        for i in range(200):
            det.update_and_score("srv", "cpu", 50.0 + (i % 5), _ts(i % 24))

        # Normal point
        normal_score = det.update_and_score("srv", "cpu", 52.0, _ts(10))
        # Extreme spike
        spike_score = det.update_and_score("srv", "cpu", 9999.0, _ts(10))

        assert spike_score >= normal_score
