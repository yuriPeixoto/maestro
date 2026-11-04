"""From flagged minutes to anomaly episodes.

A person can act on "CPU unusual from 14:02 to 14:31", not on 30 separate flagged
points. An episode is a run of flagged minutes: short gaps are bridged, and runs too
short to matter (a one-minute spike) are dropped.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

# Chosen with the evaluation bench (app.ml.evaluation): 3 minutes let recurring short
# jobs through as episodes; 5 cut the daily count by a third without missing a planted event.
MIN_FLAGGED_MINUTES = 5
MAX_GAP_MINUTES = 2

_MINUTE = pd.Timedelta(minutes=1)


@dataclass(frozen=True)
class Episode:
    start: pd.Timestamp
    end: pd.Timestamp  # exclusive: one minute after the last flagged minute
    flagged_minutes: int

    @property
    def minutes(self) -> int:
        return int((self.end - self.start) / _MINUTE)


def find_episodes(
    flags: pd.Series,
    min_flagged_minutes: int = MIN_FLAGGED_MINUTES,
    max_gap_minutes: int = MAX_GAP_MINUTES,
) -> list[Episode]:
    """Group the True minutes of `flags` (a boolean Series indexed by minute) into episodes."""
    flagged = flags.index[flags.fillna(False).astype(bool)]
    episodes: list[Episode] = []
    if len(flagged) == 0:
        return episodes

    max_step = _MINUTE * (max_gap_minutes + 1)
    run_start = previous = flagged[0]
    count = 1
    for minute in flagged[1:]:
        if minute - previous <= max_step:
            count += 1
        else:
            if count >= min_flagged_minutes:
                episodes.append(Episode(run_start, previous + _MINUTE, count))
            run_start, count = minute, 1
        previous = minute
    if count >= min_flagged_minutes:
        episodes.append(Episode(run_start, previous + _MINUTE, count))
    return episodes
