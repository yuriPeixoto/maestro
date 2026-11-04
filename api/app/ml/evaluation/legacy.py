"""The anomaly detector Maestro shipped until 2026-11, rebuilt for the bench.

One Isolation Forest per metric on rolling statistics and time features, with
contamination 0.05: by construction about 5% of the training minutes are anomalous.
Production ran it on 5-second samples; the bench runs it on per-minute values like
every other detector, which smooths noise and can only make it look better.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

_CONTAMINATION = 0.05
_ROLLING_MINUTES = 5


def _features(series: pd.Series) -> pd.DataFrame:
    hours = series.index.hour + series.index.minute / 60
    radians = 2 * np.pi * hours / 24
    features = pd.DataFrame({
        "rolling_mean": series.rolling(_ROLLING_MINUTES, min_periods=1).mean(),
        "rolling_std": series.rolling(_ROLLING_MINUTES, min_periods=2).std().fillna(0.0),
        "rate_of_change": series.diff().fillna(0.0),
        "hour_sin": np.sin(radians),
        "hour_cos": np.cos(radians),
        "day_of_week": series.index.day_of_week,
        "is_weekend": (series.index.day_of_week >= 5).astype(int),
    }, index=series.index)
    return features[series.notna()]


class LegacyDetector:
    def __init__(self) -> None:
        self._forests: dict[str, IsolationForest] = {}

    @classmethod
    def fit(cls, frame: pd.DataFrame) -> LegacyDetector:
        detector = cls()
        for metric in frame.columns:
            features = _features(frame[metric])
            if len(features) == 0:
                continue
            forest = IsolationForest(contamination=_CONTAMINATION, random_state=42, n_jobs=1)
            detector._forests[metric] = forest.fit(features.to_numpy())
        return detector

    def flag(self, frame: pd.DataFrame) -> pd.Series:
        flags = pd.Series(False, index=frame.index)
        for metric, forest in self._forests.items():
            features = _features(frame[metric])
            if len(features) == 0:
                continue
            outlier = pd.Series(forest.predict(features.to_numpy()) == -1, index=features.index)
            flags |= outlier.reindex(frame.index, fill_value=False)
        return flags
