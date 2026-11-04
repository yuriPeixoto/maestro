"""Run every detector on the same data and compare what they find.

Walk-forward, as production would run: for every test day the detectors are
refitted on the `train_days` before it, then judge that day. A server whose routine
changes (an OS upgrade, a new workload) is unusual for a few days, then normal again.

Two questions per detector:
- on a clean stretch of real data, how many episodes does it raise? Every one of
  them is either a real incident nobody labelled or a false alarm, so fewer is
  better, and the report lists them for a person to judge;
- with known anomalies planted (inject.py), which does it find, and how late?
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from app.ml.episodes import MAX_GAP_MINUTES, MIN_FLAGGED_MINUTES, Episode, find_episodes
from app.ml.evaluation.inject import InjectedEvent, inject, scenarios
from app.ml.evaluation.legacy import LegacyDetector
from app.ml.evaluation.multivariate import MultivariateDetector
from app.ml.seasonal import Z_THRESHOLD, SeasonalBaseline

# An episode that starts up to this long after an event ends still counts as finding it.
MATCH_GRACE = pd.Timedelta(minutes=10)
INJECTED_SIZES = (4.0, 8.0)

Flagger = Callable[[pd.DataFrame], pd.Series]


LEGACY = "legacy (per-metric IF, contamination 5%)"
SEASONAL = "seasonal baseline"
MULTIVARIATE = "multivariate IF on seasonal deviations"
COMBINED = "seasonal OR multivariate"
DETECTOR_NAMES = (LEGACY, SEASONAL, MULTIVARIATE, COMBINED)


@dataclass
class Detectors:
    baseline: SeasonalBaseline
    flaggers: dict[str, Flagger]


def build_detectors(train: pd.DataFrame) -> Detectors:
    baseline = SeasonalBaseline.fit(train)
    multivariate = MultivariateDetector.fit(train, baseline)
    legacy = LegacyDetector.fit(train)
    return Detectors(baseline, {
        LEGACY: legacy.flag,
        SEASONAL: baseline.flag,
        MULTIVARIATE: multivariate.flag,
        COMBINED: lambda frame: baseline.flag(frame) | multivariate.flag(frame),
    })


@dataclass
class CleanResult:
    flagged_share: float
    episodes: list[Episode]
    episodes_per_day: float


@dataclass
class EventResult:
    event: InjectedEvent
    found: bool
    delay_minutes: float | None


@dataclass
class InjectedResult:
    size: float
    events: list[EventResult]
    false_episodes_per_day: float


def evaluate_clean(flags: pd.Series, days: float) -> CleanResult:
    episodes = find_episodes(flags)
    return CleanResult(float(flags.mean()), episodes, len(episodes) / days)


def evaluate_injected(flags: pd.Series, events: list[InjectedEvent], days: float, size: float) -> InjectedResult:
    episodes = find_episodes(flags)
    matched: set[int] = set()
    results = []
    for event in events:
        hits = [i for i, ep in enumerate(episodes) if ep.start < event.end + MATCH_GRACE and ep.end > event.start]
        matched.update(hits)
        if hits:
            first = episodes[hits[0]]
            delay = max((first.start - event.start) / pd.Timedelta(minutes=1), 0.0)
            results.append(EventResult(event, True, delay))
        else:
            results.append(EventResult(event, False, None))
    false = len(episodes) - len(matched)
    return InjectedResult(size, results, false / days)


@dataclass
class BenchResult:
    train_days: int
    test: pd.DataFrame
    baselines: dict[pd.Timestamp, SeasonalBaseline]  # the baseline that judged each test day
    clean: dict[str, CleanResult]
    injected: dict[str, list[InjectedResult]]


def run_bench(frame: pd.DataFrame, train_days: int, seed: int = 7) -> BenchResult:
    window = pd.Timedelta(days=train_days)
    test = frame[frame.index >= frame.index[0] + window]
    days = len(test) / 1440
    first_train = frame[frame.index < test.index[0]]
    planted = [inject(test, first_train, spreads=size, seed=seed) for size in INJECTED_SIZES]

    clean_flags: dict[str, list[pd.Series]] = {name: [] for name in DETECTOR_NAMES}
    planted_flags: dict[str, list[list[pd.Series]]] = {name: [[] for _ in planted] for name in DETECTOR_NAMES}
    baselines: dict[pd.Timestamp, SeasonalBaseline] = {}
    for day in test.index.normalize().unique():
        train = frame[(frame.index >= day - window) & (frame.index < day)]
        today = (test.index >= day) & (test.index < day + pd.Timedelta(days=1))
        detectors = build_detectors(train)
        baselines[day] = detectors.baseline
        for name, flag in detectors.flaggers.items():
            clean_flags[name].append(flag(test[today]))
            for i, (data, _events) in enumerate(planted):
                planted_flags[name][i].append(flag(data[today]))

    clean = {name: evaluate_clean(pd.concat(flags), days) for name, flags in clean_flags.items()}
    injected = {
        name: [evaluate_injected(pd.concat(runs[i]), planted[i][1], days, size)
               for i, size in enumerate(INJECTED_SIZES)]
        for name, runs in planted_flags.items()
    }
    return BenchResult(train_days, test, baselines, clean, injected)


# ── Report ────────────────────────────────────────────────────────────────────

def render_report(result: BenchResult, label: str) -> str:
    test = result.test
    granularities = sorted({b.granularity.replace("_", " ") for b in result.baselines.values()})
    metrics = next(iter(result.baselines.values())).metrics
    lines = [
        f"# Anomaly detection bench: {label}",
        "",
        f"- Walk-forward: every test day is judged by detectors refitted on the {result.train_days} days before it.",
        f"- Test: {test.index[0]:%Y-%m-%d %H:%M} to {test.index[-1]:%Y-%m-%d %H:%M} UTC "
        f"({len(test) / 1440:.1f} days, {test.notna().any(axis=1).mean():.0%} of minutes with data)",
        f"- Seasonal baseline by {' / '.join(granularities)}; metrics: {', '.join(metrics)}",
        f"- Episode: at least {MIN_FLAGGED_MINUTES} flagged minutes, gaps up to {MAX_GAP_MINUTES} minutes bridged; "
        f"seasonal threshold {Z_THRESHOLD:g} spreads.",
        "",
        "## Clean test data (nothing planted)",
        "",
        "Every episode here is either a real incident or a false alarm.",
        "",
        "| Detector | Flagged minutes | Episodes per day |",
        "|---|---|---|",
    ]
    for name, clean in result.clean.items():
        lines.append(f"| {name} | {clean.flagged_share:.1%} | {clean.episodes_per_day:.1f} |")

    for size_index, size in enumerate(INJECTED_SIZES):
        lines += ["", f"## Planted anomalies, size {size:g} spreads", "",
                  "Found / planted, and the median delay to the first flagged minute.", ""]
        kinds = [s.kind for s in scenarios()]
        lines.append("| Detector | " + " | ".join(kinds) + " | False episodes per day |")
        lines.append("|---" * (len(kinds) + 2) + "|")
        for name, runs in result.injected.items():
            run = runs[size_index]
            cells = [_kind_cell([r for r in run.events if r.event.kind == kind]) for kind in kinds]
            lines.append(f"| {name} | " + " | ".join(cells) + f" | {run.false_episodes_per_day:.1f} |")

    lines += ["", "## Scenarios", ""]
    for scenario in scenarios():
        lines.append(f"- **{scenario.kind}**: {scenario.description}; metrics: {', '.join(scenario.metrics)}.")

    lines += ["", "## Episodes the seasonal baseline raised on the clean test data", "",
              "For a person to judge: real incident or false alarm?", ""]
    lines += _episode_lines(result)
    return "\n".join(lines) + "\n"


def _kind_cell(results: list[EventResult]) -> str:
    if not results:
        return "—"
    found = [r for r in results if r.found]
    cell = f"{len(found)}/{len(results)}"
    if found:
        delays = sorted(r.delay_minutes for r in found)
        cell += f", {delays[len(delays) // 2]:.0f} min"
    return cell


def _episode_lines(result: BenchResult) -> list[str]:
    episodes = result.clean[SEASONAL].episodes
    if not episodes:
        return ["None."]
    lines = []
    for episode in episodes:
        baseline = result.baselines[episode.start.normalize()]
        window = result.test.loc[episode.start:episode.end - pd.Timedelta(minutes=1)]
        deviations = baseline.deviations(window)
        detail = "; ".join(
            f"{d.metric} {d.value:,.1f} (normal {d.normal_low:,.1f}–{d.normal_high:,.1f}, z {d.z:+.1f})"
            for d in deviations[:3]
        ) or "no single metric above the threshold"
        lines.append(f"- {episode.start:%a %Y-%m-%d %H:%M}–{episode.end:%H:%M} UTC "
                     f"({episode.minutes} min): {detail}")
    return lines
