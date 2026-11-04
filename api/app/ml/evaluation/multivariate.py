"""One Isolation Forest per server, over every metric at once (bench only).

The seasonal baseline judges each metric alone. Some trouble only shows as a
combination: disk writes and process count both a little high while CPU looks fine.
This model sees all metrics of a minute together, each already expressed as its
deviation from the seasonal baseline, so routine (office hours, nightly jobs) is
not mistaken for an anomaly.

Its threshold comes from its own training scores (a high quantile), not from a fixed
share of anomalies. On the first real data it found nothing the seasonal baseline
missed, so production does not run it; the bench keeps it for comparison.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from app.ml.seasonal import SeasonalBaseline

# Deviations are clipped so one huge value does not dominate the trees.
Z_CLIP = 20.0
N_ESTIMATORS = 200
RANDOM_STATE = 42

SCORE_QUANTILE = 0.999


@dataclass
class MultivariateDetector:
    baseline: SeasonalBaseline
    forest: IsolationForest
    threshold: float

    @classmethod
    def fit(cls, frame: pd.DataFrame, baseline: SeasonalBaseline,
            score_quantile: float = SCORE_QUANTILE) -> MultivariateDetector:
        features = _features(baseline, frame).dropna()
        forest = IsolationForest(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, n_jobs=1)
        forest.fit(features.to_numpy())
        training_scores = -forest.decision_function(features.to_numpy())
        return cls(baseline, forest, float(np.quantile(training_scores, score_quantile)))

    def scores(self, frame: pd.DataFrame) -> pd.Series:
        """Higher is more unusual; NaN for minutes with missing data."""
        features = _features(self.baseline, frame)
        complete = features.notna().all(axis=1)
        out = pd.Series(np.nan, index=frame.index)
        if complete.any():
            out[complete] = -self.forest.decision_function(features[complete].to_numpy())
        return out

    def flag(self, frame: pd.DataFrame) -> pd.Series:
        return self.scores(frame) >= self.threshold


def _features(baseline: SeasonalBaseline, frame: pd.DataFrame) -> pd.DataFrame:
    return baseline.zscores(frame).clip(-Z_CLIP, Z_CLIP)
