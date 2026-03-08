# ADR-007: Alerting Pipeline Architecture

**Status**: Proposed
**Date**: 2026-03-08
**Deciders**: Yuri Peixoto

---

## Context

Maestro must notify operators when servers exhibit abnormal behavior — either through metric threshold violations or agent unavailability. The alerting system must:

- Evaluate conditions continuously against incoming data (not on-demand per user request)
- Fire each alert event once, not once per offending data point (deduplication)
- Support evolving rule types: static thresholds in Phase 2, ML anomaly scores in Phase 3
- Handle "agent offline" detection separately from metric alerting (different severity and cooldown)
- Deliver notifications to configurable channels (webhook initially, then email/Slack)

---

## Decision

### Overall Data Flow

```
ClickHouse (metrics data)
       │
       ▼
Python Evaluator Worker  ←── Rules config (YAML or DB)
       │
       ▼
Alert Manager
  ├── Deduplication
  ├── Cooldown (configurable, default 15 min)
  └── State machine: firing → resolved
       │
       ▼
Notification Dispatcher
  ├── Webhook (Phase 2)
  ├── Email / SMTP (Phase 3)
  └── Slack webhook (Phase 3)
```

### Why NOT Alerting in the API Request Path

A naive implementation would check thresholds inside the REST API handler — when the dashboard queries metrics, it also evaluates alert conditions and fires notifications. This is explicitly rejected:

- Alerts must fire even when no user is viewing the dashboard
- API response latency must not be affected by notification I/O (webhook/SMTP calls)
- Alert state (firing/resolved) must be persisted — it cannot be derived per-request
- Multiple concurrent API requests would evaluate the same alert condition redundantly, causing duplicate fires

The evaluator worker is a **separate long-running process** that polls ClickHouse independently of the API.

### Evaluator Worker

The evaluator worker runs as a background process (or a separate FastAPI startup task using `asyncio`):

1. On a configurable interval (default: every 30s), queries ClickHouse for recent metric windows per active rule
2. Evaluates each rule's condition against the window
3. Passes events (condition met / condition cleared) to the Alert Manager

The evaluation interval is intentionally coarser than the data collection interval (30s vs. 5s) — alerting on every raw data point is unnecessary and amplifies noise.

### Alert Manager

The Alert Manager maintains alert state and enforces:

**Deduplication**: An alert `(server_id, metric_name, rule_id)` transitions to `firing` state once and stays there until the condition clears. It does not re-fire on every evaluation cycle while the condition is active.

**Cooldown**: After an alert resolves, it cannot re-fire for a configurable cooldown period (default: 15 minutes). This prevents flapping alerts from spamming notification channels.

**State Machine**:
```
INACTIVE ──[condition met]──► FIRING ──[condition cleared]──► RESOLVED
                                                                   │
                                              [cooldown elapsed]   │
                                         ◄─────────────────────────┘
                                         INACTIVE
```

**Phase 2 — Static Threshold Rules**:
```yaml
# Example rule
- id: cpu_high
  server_id: "*"          # applies to all servers
  metric: cpu_usage_percent
  condition: "value > 90"
  consecutive_readings: 3  # must exceed threshold for 3 consecutive evaluations
  cooldown_minutes: 15
  severity: warning
```

The `consecutive_readings` requirement prevents single-spike false positives.

**Phase 3 — ML Score-Based Rules**:

Static threshold rules are supplemented (not replaced) by ML rules:
```yaml
- id: anomaly_isolation_forest
  server_id: "*"
  source: ml_score
  condition: "anomaly_score < -0.3"   # Isolation Forest: negative = anomalous
  cooldown_minutes: 30
  severity: info
```

The Isolation Forest score for a data point is stored alongside the metric in ClickHouse (or a separate `anomaly_scores` table) and evaluated by the same worker.

### Heartbeat Alerting — Separate Pipeline

Heartbeat alerting is handled separately from metric alerting:

- **Trigger**: no heartbeat received from `server_id` for more than 90s
- **Detection**: the FastAPI heartbeat tracker (Phase 1, Issue 7) maintains a `last_seen` timestamp per server
- **Severity**: `critical` — a missing heartbeat means the agent is down, not just a metric spike
- **Cooldown**: 30 minutes (re-notify if the server stays offline)
- **State**: a separate `agent_status` table tracks `online` / `offline` per server

Heartbeat alerts do not go through the metric evaluator worker — they are emitted by the heartbeat tracker directly to the Alert Manager.

**Rationale**: Heartbeat loss is a fundamentally different signal from a metric anomaly. Mixing them in the same evaluation pipeline would complicate rule logic and severity handling.

### Notification Channels

**Phase 2 — Webhook only**:
```
POST {webhook_url}
Content-Type: application/json

{
  "alert_id": "cpu_high",
  "server_id": "prod-web-01",
  "metric": "cpu_usage_percent",
  "value": 94.2,
  "severity": "warning",
  "fired_at": "2026-03-08T14:32:00Z"
}
```

Webhook delivery is asynchronous — the Alert Manager enqueues the notification and a dispatcher sends it without blocking alert state updates.

**Phase 3 — Additional channels**:
- Email via SMTP (Python `smtplib` or `aiosmtplib` for async)
- Slack via incoming webhook URL

Channel routing is configurable per rule — one rule can notify both webhook and Slack simultaneously.

---

## Alternatives Considered

| Option | Verdict | Reason |
|--------|---------|--------|
| Alert in API request path | Rejected | Misses alerts when dashboard is not open; adds latency; causes duplicate fires |
| External Alertmanager (Prometheus) | Deferred | Adds infrastructure dependency; overkill for Phase 2; may be reconsidered for Phase 5 |
| In-database triggers (ClickHouse) | Rejected | ClickHouse does not support row-level triggers; materialised views approximate it but are limited |
| PagerDuty / OpsGenie integration | Deferred | Phase 5 consideration; webhook in Phase 2 is sufficient to forward to these tools |

---

## Consequences

**Positive**:
- Alerts fire even when no user is active on the dashboard
- Deduplication and cooldown prevent alert fatigue from flapping conditions
- The state machine makes `resolved` notifications possible (closing the loop)
- Heartbeat and metric alerting are cleanly separated by concern

**Negative**:
- The evaluator worker is an additional process to operate and monitor
- There is a latency between a condition occurring and alert firing — up to one evaluation interval (30s) plus notification dispatch time
- Alert state is stored in PostgreSQL (or ClickHouse) — this must be schema-managed alongside the rest of the application
