"""What is normal for this server at this hour: the seasonal baseline.

Servers follow a routine: quiet nights, busier office hours, lighter weekends.
The baseline learns, for each metric and each hour of the week, the median and a
robust spread (MAD) from past weeks. A value is then judged against its own hour:
"CPU at 35%, normal for Tuesday 14h is 9–14%" instead of a single global limit.

Rates (bytes per second) are heavy-tailed: a backup moves 100 times the usual
traffic. They are compared on a log scale, where "ten times the usual" is a
deviation of fixed size whatever the usual is.

With less than about two weeks of history an hour of the week has too few samples,
so the baseline falls back to the hour of the day. It is meant to be refitted every
day on a recent window, so it follows a server whose routine changes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

_MAD_TO_STD = 1.4826
HOURS_PER_WEEK = 168

HOUR_OF_WEEK = "hour_of_week"
HOUR_OF_DAY = "hour_of_day"

_LOG_SCALED_SUFFIX = "_per_sec"

# An hour of the week needs this many minutes of history (two weeks at 75% coverage).
MIN_MINUTES_PER_CELL = 90
# A cell's spread is never below this fraction of the metric's overall spread, so a
# flat night does not turn a small wobble into a huge deviation.
SPREAD_FLOOR_FRACTION = 0.5
# A metric that barely varies (total disk size) carries no signal.
_CONSTANT_RELATIVE_SPREAD = 1e-6

# "Normal" shown to people: median ± 2 spreads (about 95% of ordinary minutes).
NORMAL_BAND_SPREADS = 2.0

# Chosen with the evaluation bench (app.ml.evaluation): on the first real server, 5
# spreads with 5-minute episodes raised about 3 episodes a day, all of them real events,
# and found every planted spike, level shift and leak.
Z_THRESHOLD = 5.0


def robust_spread(frame: pd.DataFrame) -> pd.Series:
    """1.4826 × MAD per column, falling back to the standard deviation when MAD is 0."""
    mad = (frame - frame.median()).abs().median() * _MAD_TO_STD
    return mad.where(mad > 0, frame.std()).fillna(0.0)


def cell_of(index: pd.DatetimeIndex, granularity: str) -> np.ndarray:
    if granularity == HOUR_OF_WEEK:
        return (index.day_of_week * 24 + index.hour).to_numpy()
    return index.hour.to_numpy()


def _is_log_scaled(metric: str) -> bool:
    return metric.endswith(_LOG_SCALED_SUFFIX)


def to_model_scale(frame: pd.DataFrame) -> pd.DataFrame:
    """Rates on log1p, the rest as is."""
    scaled = frame.copy()
    for metric in scaled.columns:
        if _is_log_scaled(metric):
            scaled[metric] = np.log1p(scaled[metric].clip(lower=0))
    return scaled


def _from_model_scale(metric: str, value: float) -> float:
    return float(np.expm1(value)) if _is_log_scaled(metric) else value


@dataclass(frozen=True)
class Deviation:
    metric: str
    peak_at: pd.Timestamp
    value: float
    z: float
    normal_low: float
    normal_high: float


@dataclass
class SeasonalBaseline:
    granularity: str
    median: pd.DataFrame  # index: cell, columns: metric; on the model scale
    spread: pd.DataFrame
    metrics: list[str]

    @classmethod
    def fit(cls, frame: pd.DataFrame) -> SeasonalBaseline:
        data = to_model_scale(frame)
        overall = robust_spread(data)
        scale = data.median().abs() + 1.0
        metrics = [m for m in data.columns
                   if data[m].notna().any() and overall[m] > _CONSTANT_RELATIVE_SPREAD * scale[m]]
        data = data[metrics]

        granularity = HOUR_OF_WEEK if _enough_per_week_cell(data) else HOUR_OF_DAY
        cells = cell_of(data.index, granularity)
        median = data.groupby(cells).median()
        deviation = (data - median.reindex(cells).to_numpy()).abs()
        mad = deviation.groupby(cells).median() * _MAD_TO_STD
        spread = mad.clip(lower=overall[metrics] * SPREAD_FLOOR_FRACTION, axis=1)
        return cls(granularity, median, spread, metrics)

    def expected(self, frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """The median and spread (model scale) that apply to each minute of `frame`."""
        cells = cell_of(frame.index, self.granularity)
        median = self.median.reindex(cells).set_axis(frame.index)
        spread = self.spread.reindex(cells).set_axis(frame.index)
        return median, spread

    def zscores(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Deviation of each value from its hour, in spreads. NaN where data or history is missing."""
        median, spread = self.expected(frame)
        return (to_model_scale(frame[self.metrics]) - median) / spread

    def flag(self, frame: pd.DataFrame, z_threshold: float = Z_THRESHOLD) -> pd.Series:
        return (self.zscores(frame).abs() >= z_threshold).any(axis=1)

    def deviations(self, frame: pd.DataFrame, z_threshold: float = Z_THRESHOLD) -> list[Deviation]:
        """The metrics that left their normal range in `frame` (one episode), worst first."""
        z = self.zscores(frame)
        median, spread = self.expected(frame)
        out = []
        for metric in self.metrics:
            column = z[metric].dropna()
            if column.empty or column.abs().max() < z_threshold:
                continue
            peak = column.abs().idxmax()
            center, width = median.at[peak, metric], NORMAL_BAND_SPREADS * spread.at[peak, metric]
            out.append(Deviation(
                metric=metric,
                peak_at=peak,
                value=float(frame.at[peak, metric]),
                z=float(column[peak]),
                normal_low=max(_from_model_scale(metric, center - width), 0.0),
                normal_high=_from_model_scale(metric, center + width),
            ))
        return sorted(out, key=lambda d: abs(d.z), reverse=True)


def _enough_per_week_cell(frame: pd.DataFrame) -> bool:
    present = frame.notna().any(axis=1)
    counts = pd.Series(present.to_numpy()).groupby(cell_of(frame.index, HOUR_OF_WEEK)).sum()
    return len(counts) == HOURS_PER_WEEK and counts.min() >= MIN_MINUTES_PER_CELL
