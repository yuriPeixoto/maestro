# ADR-010: Anomaly Detection and Capacity Planning, Measured

**Status**: Accepted (supersedes ADR-005)
**Date**: 2026-11-04
**Deciders**: Yuri Peixoto

---

## Context

ADR-005 chose Isolation Forest, then River, then Prophet, on general arguments. None of them was ever
measured against real data. A review in 2026-11, on one production web server, found:

- **Isolation Forest** ran one model per metric (ADR-005 asked for one per server) on 5-second samples,
  with `contamination=0.05`. By construction it marked about 5% of every period as anomalous, and it
  scored points, not episodes. Nobody could act on 470 flags a day.
- **River** (HalfSpaceTrees) scored about 10% of all samples at 0.5 or more, and wrote its scores under the
  same `anomaly_scores` key as Isolation Forest, so each model overwrote the other's.
- **Prophet** forecast disk, memory and CPU daily averages. CPU and memory averages have no trend, so
  "days to 90%" never happens for them. Disk usage moves in steps, which a smooth trend model mistakes for
  growth.
- All of it ran inside the API's event loop.

## Decision

Measure first, then keep what earns its place.

### The evaluation bench (`api/app/ml/evaluation`)

`python -m app.ml.evaluation` has three commands:

- **`export`** reads one value per metric per minute with read-only queries.
- **`run`** compares the anomaly detectors walk-forward: every test day is judged by detectors refitted on
  the 14 days before it, as production refits daily. It answers two questions:
  - how many episodes does each detector raise on real data with nothing planted? Each one is either an
    incident or a false alarm, and the report lists them for a person to judge;
  - which planted anomalies does it find, and how late? The planted kinds are a spike, a level shift, a
    slow leak, office-hours load at night, and two metrics moving together.
- **`forecast`** backtests the capacity models from rolling origins against what happened.

### Results (one web server, 23 days, 7 metrics)

| Anomaly detector | Episodes per day, real data | Planted at 8 spreads: spike / shift / leak / off-hours / joint |
|---|---|---|
| Isolation Forest per metric, contamination 5% (the old one) | 17.6 | 5/5, 5/5, 3/3, 3/5, 5/5, by flagging 18% of all minutes |
| **Seasonal baseline** (z ≥ 5, episodes of 5+ minutes) | **2.9** | 4/5, 5/5, 3/3, 4/5, 1/5 |
| Isolation Forest per server on seasonal deviations | 0.2 | 0/5, 1/5, 0/3, 0/5, 0/5 |

| Disk forecast, mean absolute error (pp) | 1 day | 7 days |
|---|---|---|
| **Theil-Sen since the last level shift** | 0.34 | **0.42** |
| Ordinary least squares | 0.40 | 0.50 |
| Tomorrow equals today | 0.32 | 0.76 |
| Prophet | 0.55 | 1.20 |

For CPU and memory averages, no model beat "tomorrow equals today" by a useful margin.

### What ships

- **Seasonal baseline** (`app/ml/seasonal.py`)
  - For each metric and hour of the week, it learns the median and a robust spread (1.4826 × MAD) from the
    last 28 days. It falls back to the hour of the day with less than two weeks of history.
  - Rates are compared on a log scale, because traffic is heavy-tailed: a backup moves 100 times the usual
    bytes.
  - The baseline is refitted daily, so it follows a server whose routine changes. After an OS upgrade the
    test server was unusual for a day, then normal again.
  - It explains itself: "CPU 44%, normal 5–8% for this hour".
- **Episodes** (`app/ml/episodes.py`, `anomaly_episodes`): runs of 5 or more flagged minutes, with gaps up
  to 2 minutes bridged. Each episode stores the metrics that deviated, their values, the normal range and
  the deviation in spreads. The 2.9 episodes a day on the test server were all real events: the OS upgrade,
  backups, bursts of disk writes.
- **Scores**: one per metric per minute in `anomaly_scores` (`model_version = 'seasonal'`). |z| is mapped
  to [0, 1] with the threshold at 0.5, so the chart overlay and the ML alert mode keep their contract.
- **Disk forecast** (`app/ml/forecaster.py`): a Theil-Sen line on the stretch after the last level shift,
  with a band of two robust spreads of the residuals.
- **CPU and memory capacity** (`app/peaks.py`): each day's highest 5-minute average, the headroom below
  the critical limit on the worst day, and the trend of the peaks.

### What goes

Isolation Forest, the feature pipeline (`metric_features` is no longer written), the model store on disk,
River and Prophet (with cmdstan). The bench keeps the old Isolation Forest and a multivariate one so the
comparison can be repeated.

### Where it runs

ML work runs in the worker process, never in the API (see the README), and its CPU-heavy steps run in one
child process with nice 10 (`app/ml/pool.py`).

## Consequences

**Positive**
- About 3 episodes a day instead of 17, each with an explanation a person can check.
- No model files, and a smaller dependency set: River, Prophet, cmdstan, matplotlib, joblib and others are
  gone.
- Every threshold in this ADR came from the bench and can be re-measured.

**Negative / open**
- All numbers come from one server and 23 days. Rerun the bench when more servers report, and when four
  weeks give the baseline its hour-of-the-week profile.
- The baseline is per metric. Two metrics that each move a little (the "joint" case, 1 of 5 found) can go
  unnoticed. The multivariate model did worse here, so it is not the fix.
- A slow leak is found late: 2 to 4 hours, once the climb passes 5 spreads for its hour.
- `metric_features` still exists and expires by TTL; drop it by hand when convenient.
