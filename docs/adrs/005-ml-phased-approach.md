# ADR-005: ML Stack — Phased Approach

**Status**: Accepted
**Date**: 2026-03-08
**Deciders**: Yuri Peixoto

---

## Context

Maestro's long-term value proposition includes intelligent anomaly detection — moving beyond static "CPU > 90%" thresholds to dynamic, context-aware alerting. However, ML models require historical data to train, and on day one there is no data. The ML stack must be introduced incrementally without blocking the platform from being useful early.

Additionally, different ML tools serve different purposes:
- Anomaly detection requires sub-minute resolution and operates in real-time
- Capacity planning requires weeks of history and operates on daily granularity

Conflating these two concerns into one tool is a design mistake.

---

## Decision: Phased ML Introduction

### Phase 1: No ML — Static Thresholds + Baseline Collection

In Phase 1 there is no ML. The platform uses simple static threshold rules (e.g., CPU > 90% for 3 consecutive readings). This is intentional:

- The system becomes useful immediately without requiring training data
- Agent data accumulates in ClickHouse during this phase
- Operators learn what "normal" looks like for their servers
- This phase produces the labeled baseline that Phase 2/3 will consume

**Duration**: First production deployment through roughly 2–4 weeks of real traffic.

### Phase 2/3: scikit-learn Isolation Forest — Anomaly Detection

Once sufficient data has accumulated (recommended: 1+ week of normal operation), introduce Isolation Forest for multivariate anomaly detection.

**Why Isolation Forest**:
- Does not require labeled anomalies — unsupervised, works on normal operational data alone
- Multivariate: handles CPU + memory + disk I/O together, detecting correlated anomalies that per-metric thresholds miss (e.g., CPU normal but memory slowly leaking)
- Produces a continuous anomaly score, not a binary flag — enables tunable sensitivity
- Fast inference: trained model scores a new data point in microseconds
- Mature scikit-learn implementation with no additional infrastructure

**Feature Engineering** (required before training):

| Feature | Rationale |
|---------|-----------|
| `rolling_mean_5m` | Smooths noise; captures sustained deviation vs. spikes |
| `rolling_std_5m` | Captures volatility — high std is itself an anomaly signal |
| `rate_of_change` | Detects sudden jumps even when absolute value is not extreme |
| `hour_sin`, `hour_cos` | Cyclic encoding of hour-of-day — preserves continuity between 23:00 and 00:00 |
| `day_of_week` | Weekly seasonality (weekday vs. weekend load patterns) |
| `is_weekend` | Binary flag to distinguish weekend baseline from weekday baseline |

Raw metric values alone are insufficient — the model must know whether a given CPU level is anomalous given the time of day and recent trend.

**Training cadence**: Retrain per server once per week using the previous 4 weeks of data.

**Model scope**: One model per server (not one global model). Servers have different baselines; a shared model would produce poor results.

### Phase 3+: River — Online/Streaming ML

After Isolation Forest is established, introduce [River](https://riverml.xyz/) for online learning:

- River updates the model incrementally with each incoming data point — no batch retraining required
- Dynamic thresholds adapt as servers evolve (e.g., a new microservice deployed that permanently raises baseline CPU)
- River's `HalfSpaceTrees` or `SNARIMAX` are suitable for streaming anomaly detection
- Isolation Forest remains as the cold-start model; River takes over once it has seen sufficient data

**River does not replace Isolation Forest** — it extends it. Isolation Forest provides the initial trained state; River refines it online.

### Phase 4: Prophet — Capacity Planning Only

[Prophet](https://facebook.github.io/prophet/) is introduced in Phase 4 **exclusively for capacity planning forecasting**:

- "Disk will be full in X days"
- "Memory runway at current growth rate: 3 weeks"
- Forecasting CPU headroom for planned capacity decisions

**Why Prophet is wrong for real-time anomaly detection**:

| Concern | Detail |
|---------|--------|
| Temporal granularity | Prophet is designed for daily/weekly seasonality. It was built for business metrics (daily sales, weekly signups). It operates at day-level granularity. |
| Latency | Prophet fits a Stan model per forecast call. This takes seconds — incompatible with 5s metric resolution and real-time alerting. |
| Data requirements | Prophet requires weeks of history to fit seasonal components reliably. It produces unreliable forecasts on short histories. |
| Dependency weight | PyStan (Prophet's backend) is a heavy C++ dependency with slow install times and occasional platform compatibility issues. |
| Stationarity | Operational metrics (CPU, memory) are not stationary. Prophet assumes decomposable trend + seasonality — a good model for business KPIs, wrong for system metrics that can spike non-seasonally at any moment. |

**Prophet's correct role**: Given 30+ days of historical data, forecast the next 7-30 days of disk usage trend. This is a planning tool, not an operational alerting tool.

---

## Alternatives Considered

| Tool | Verdict | Reason |
|------|---------|--------|
| Prophet for anomaly detection | Rejected | Wrong granularity, high latency, heavy dependency |
| LSTM / deep learning | Deferred | Requires large datasets and GPU; overkill for Phase 2/3 |
| Z-score static baseline | Insufficient | Single-metric, no multivariate correlation, no adaptation |
| One global Isolation Forest | Rejected | Different servers have different baselines; per-server models required |

---

## Consequences

**Positive**:
- Platform is useful on day one (Phase 1) without any ML infrastructure
- Isolation Forest handles multivariate anomalies that static thresholds miss
- River enables continuous adaptation without expensive retraining jobs
- Prophet is used only where it excels — multi-day forecasting

**Negative**:
- Feature engineering pipeline (rolling windows, cyclic encoding) must be built before training — non-trivial engineering effort
- Per-server models multiply storage and training compute linearly with fleet size
- River requires careful handling of concept drift (a sudden permanent change in baseline must not be learned as "normal" too quickly)
