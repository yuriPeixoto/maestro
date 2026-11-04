"""
The evaluation bench: planted anomalies are labelled where they were written, an
episode counts as finding an event only when it overlaps it, and the forecast
backtest spots level shifts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.ml.episodes import Episode
from app.ml.evaluation.bench import evaluate_injected
from app.ml.evaluation.forecast_bench import theil_sen_since_shift
from app.ml.forecaster import last_level_shift
from app.ml.evaluation.inject import InjectedEvent, inject
from app.ml.frames import ANOMALY_METRICS


def _frame(days: int, start: str = "2026-10-01", seed: int = 3) -> pd.DataFrame:
    index = pd.date_range(start, periods=days * 1440, freq="1min", tz="UTC", name="minute")
    rng = np.random.default_rng(seed)
    data = {metric: 50 + rng.normal(0, 2, len(index)) for metric in ANOMALY_METRICS}
    return pd.DataFrame(data, index=index)


class TestInject:
    def test_events_are_written_where_they_are_labelled(self):
        train, test = _frame(7), _frame(3, start="2026-10-08", seed=4)

        planted, events = inject(test, train, spreads=8.0, seed=1)

        assert {e.kind for e in events} == {"spike", "level_shift", "slow_ramp", "off_hours", "joint"}
        for event in events:
            window = (test.index >= event.start) & (test.index < event.end)
            assert (planted.loc[window, list(event.metrics)] >= test.loc[window, list(event.metrics)]).all().all()
        changed = (planted != test).any(axis=1)
        labelled = pd.Series(False, index=test.index)
        for event in events:
            labelled |= (test.index >= event.start) & (test.index < event.end)
        assert not (changed & ~labelled).any()

    def test_events_do_not_overlap(self):
        _planted, events = inject(_frame(3, start="2026-10-08"), _frame(7), spreads=4.0, seed=2)
        for a, b in zip(events, events[1:]):
            assert a.end <= b.start


def _event(start_minute: int, minutes: int) -> InjectedEvent:
    start = pd.Timestamp("2026-11-01", tz="UTC") + pd.Timedelta(minutes=start_minute)
    return InjectedEvent("spike", ("cpu_usage_percent",), start, start + pd.Timedelta(minutes=minutes), "+8")


def _flags_for(episodes: list[Episode], length: int = 300) -> pd.Series:
    index = pd.date_range("2026-11-01", periods=length, freq="1min", tz="UTC")
    flags = pd.Series(False, index=index)
    for episode in episodes:
        flags[(index >= episode.start) & (index < episode.end)] = True
    return flags


class TestMatching:
    def test_found_late_missed_and_false(self):
        t0 = pd.Timestamp("2026-11-01", tz="UTC")
        found = Episode(t0 + pd.Timedelta(minutes=12), t0 + pd.Timedelta(minutes=20), 8)
        false = Episode(t0 + pd.Timedelta(minutes=200), t0 + pd.Timedelta(minutes=210), 10)
        events = [_event(10, 5), _event(100, 5)]

        result = evaluate_injected(_flags_for([found, false]), events, days=1.0, size=8.0)

        assert [(r.found, r.delay_minutes) for r in result.events] == [(True, 2.0), (False, None)]
        assert result.false_episodes_per_day == 1.0


class TestLevelShift:
    def test_the_last_jump_is_found(self):
        days = pd.date_range("2026-10-01", periods=20, freq="D")
        series = pd.Series(np.r_[np.linspace(45, 46, 12), np.linspace(47.5, 47.7, 8)], index=days)

        assert last_level_shift(series.to_numpy()) == 12

    def test_the_trend_after_the_jump_ignores_the_level_before_it(self):
        days = pd.date_range("2026-10-01", periods=20, freq="D")
        series = pd.Series(np.r_[np.full(12, 40.0), 50 + 0.1 * np.arange(8)], index=days)

        forecast = theil_sen_since_shift(series, 3)

        np.testing.assert_allclose(forecast, [50.8, 50.9, 51.0], atol=1e-9)
