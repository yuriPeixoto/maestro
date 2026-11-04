"""
The seasonal baseline judges a value against its own hour, and turns flagged
minutes into episodes a person can read.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.ml.episodes import find_episodes
from app.ml.seasonal import HOUR_OF_DAY, HOUR_OF_WEEK, SeasonalBaseline


def _routine(days: int, seed: int = 1) -> pd.DataFrame:
    """CPU at 5% at night and 30% from 9h to 17h, plus noise; disk writes around 200 kB/s."""
    index = pd.date_range("2026-10-05", periods=days * 1440, freq="1min", tz="UTC", name="minute")
    rng = np.random.default_rng(seed)
    office = (index.hour >= 9) & (index.hour < 17)
    return pd.DataFrame({
        "cpu_usage_percent": np.where(office, 30.0, 5.0) + rng.normal(0, 1, len(index)),
        "disk_write_bytes_per_sec": 200_000 * np.exp(rng.normal(0, 0.2, len(index))),
        "disk_total_bytes": np.full(len(index), 336e9),
    }, index=index)


def _day(frame: pd.DataFrame, offset_days: int) -> pd.DataFrame:
    start = frame.index[0] + pd.Timedelta(days=offset_days)
    return frame.loc[start:start + pd.Timedelta(minutes=1439)]


class TestBaseline:
    def test_office_hours_load_is_normal_by_day_and_unusual_at_night(self):
        history = _routine(14)
        baseline = SeasonalBaseline.fit(history)
        day = _day(_routine(15, seed=2), 14).copy()

        assert not baseline.flag(day).any()

        night = (day.index.hour == 3) & (day.index.minute < 20)
        day.loc[night, "cpu_usage_percent"] = 30.0
        flags = baseline.flag(day)
        assert flags[night].all()
        assert flags.sum() == night.sum()

    def test_rates_are_judged_on_a_log_scale(self):
        baseline = SeasonalBaseline.fit(_routine(14))
        day = _day(_routine(15, seed=3), 14).copy()
        window = (day.index.hour == 10) & (day.index.minute < 10)

        day.loc[window, "disk_write_bytes_per_sec"] = 1.5 * 200_000
        assert not baseline.flag(day)[window].any()

        day.loc[window, "disk_write_bytes_per_sec"] = 20 * 200_000
        assert baseline.flag(day)[window].all()

    def test_a_constant_metric_is_left_out(self):
        assert "disk_total_bytes" not in SeasonalBaseline.fit(_routine(14)).metrics

    def test_hour_of_week_needs_two_weeks_of_history(self):
        assert SeasonalBaseline.fit(_routine(7)).granularity == HOUR_OF_DAY
        assert SeasonalBaseline.fit(_routine(14)).granularity == HOUR_OF_WEEK

    def test_deviation_says_what_was_normal(self):
        baseline = SeasonalBaseline.fit(_routine(14))
        day = _day(_routine(15, seed=4), 14).copy()
        night = (day.index.hour == 3) & (day.index.minute < 20)
        day.loc[night, "cpu_usage_percent"] = 30.0

        deviations = baseline.deviations(day[night])

        assert [d.metric for d in deviations] == ["cpu_usage_percent"]
        cpu = deviations[0]
        assert cpu.value == 30.0
        assert cpu.normal_low < 5.0 < cpu.normal_high < 30.0
        assert cpu.z > 5

    def test_rate_bands_never_go_negative(self):
        baseline = SeasonalBaseline.fit(_routine(14))
        day = _day(_routine(15, seed=5), 14).copy()
        day["disk_write_bytes_per_sec"] = 50e6

        deviation = baseline.deviations(day.iloc[:10])[0]

        assert deviation.metric == "disk_write_bytes_per_sec"
        assert 0 <= deviation.normal_low < 200_000 < deviation.normal_high


def _flags(minutes: list[int], length: int = 60) -> pd.Series:
    index = pd.date_range("2026-11-01", periods=length, freq="1min", tz="UTC")
    flags = pd.Series(False, index=index)
    flags.iloc[minutes] = True
    return flags


class TestEpisodes:
    def test_short_runs_are_dropped(self):
        assert find_episodes(_flags([10, 11, 12])) == []

    def test_gaps_up_to_two_minutes_are_bridged(self):
        episodes = find_episodes(_flags([10, 11, 14, 15, 16, 19, 20]))

        assert len(episodes) == 1
        assert episodes[0].minutes == 11
        assert episodes[0].flagged_minutes == 7

    def test_a_longer_gap_starts_a_new_episode(self):
        episodes = find_episodes(_flags([*range(5, 11), *range(20, 26)]))

        assert [(e.start.minute, e.end.minute) for e in episodes] == [(5, 11), (20, 26)]
