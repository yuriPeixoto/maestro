# Maestro — Product Roadmap

> **Platform**: On-premise observability for engineering teams.
> **Architecture**: Go Agent → Redis Streams → Python FastAPI → ClickHouse → React Frontend.

---

## Phase 1 — Foundation: Data Pipeline (current)

**Goal**: Working end-to-end pipeline from agent to ClickHouse. No frontend yet. Verifiable via API.

| # | Title | Description |
|---|-------|-------------|
| 1 | Go agent: metric collection | Implement metric collection with configurable sampling rates using gopsutil (CPU 5s, memory 15s, disk I/O 5s, disk space 60s, network 5s, process count 30s) |
| 2 | Go agent: local ring buffer | Implement local ring buffer for Redis unavailability to prevent data loss during outages |
| 3 | Go agent: heartbeat mechanism | Implement heartbeat emission at 30s interval, distinct from metric payloads |
| 4 | Go agent: metric naming convention | Enforce Prometheus-style metric naming convention (snake_case, e.g. cpu_usage_percent) across all collected metrics |
| 5 | ClickHouse: schema design | Define and create schema with MergeTree, partitioning by month, sort key (server_id, metric_name, timestamp), 90-day TTL, LowCardinality for metric names |
| 6 | FastAPI: Redis Streams consumer | Implement Redis Streams consumer that reads metric batches from the agent and writes them to ClickHouse |
| 7 | FastAPI: heartbeat tracking | Implement heartbeat tracking — detect servers offline when no heartbeat received for more than 90s |
| 8 | FastAPI: metric query REST API | Implement REST API endpoints for querying metrics (last N minutes per server/metric combination) |
| 9 | Docs: ADRs 004–007 | Write ADR-004 (ClickHouse schema), ADR-005 (ML phased approach), ADR-006 (Frontend stack), ADR-007 (Alerting pipeline) |

---

## Phase 2 — Dashboard & Basic Alerting

**Goal**: Working frontend with real data + static threshold alerting.

| # | Title | Description |
|---|-------|-------------|
| 1 | Frontend: project setup | Bootstrap Vite + React + TypeScript + Tailwind + TanStack Query + Zustand + Recharts |
| 2 | Frontend: server list view | Implement server list view showing online/offline status derived from heartbeat data |
| 3 | Frontend: per-server metric dashboard | Implement per-server dashboard with time-series charts for CPU, memory, disk, and network |
| 4 | Frontend: metric summary cards | Implement metric summary cards showing current values and trend indicators (up/down/stable) |
| 5 | Alerting: static threshold rules engine | Implement configurable static threshold rules per metric per server |
| 6 | Alerting: deduplication and cooldown | Implement alert deduplication and cooldown mechanism (one alert per event, not per data point) |
| 7 | Alerting: webhook notification channel | Implement webhook notification channel for alert delivery |
| 8 | Demo: realistic data seeder | Implement data seeder with configurable patterns, seasonality, and injected anomalies for demos |

---

## Phase 3 — ML Intelligence

**Goal**: Replace static thresholds with ML-powered dynamic anomaly detection.

| # | Title | Description |
|---|-------|-------------|
| 1 | Feature engineering pipeline | Build rolling mean/std (5m), rate of change, cyclic hour encoding (sin/cos), day-of-week, and is_weekend features |
| 2 | Isolation Forest model | Train multivariate anomaly detection model per server using scikit-learn Isolation Forest |
| 3 | Dynamic alert thresholds | Replace static threshold rules with ML anomaly score-based alert triggers |
| 4 | ML model persistence | Implement save/load for trained models using pickle with metadata versioning |
| 5 | River integration | Integrate River (online ML) for streaming dynamic threshold updates as new data accumulates |
| 6 | Dashboard: anomaly visualization | Highlight anomalous data points on metric charts with anomaly score overlay |

---

## Phase 4 — Capacity Planning & Ecosystem

**Goal**: Predictive forecasting + Orquestra integration.

| # | Title | Description |
|---|-------|-------------|
| 1 | Prophet integration | Implement capacity forecasting for disk, memory, and CPU trends using Prophet (days/weeks ahead) |
| 2 | Forecast dashboard | Build "disk will be full in X days" visual runway charts with forecast data |
| 3 | Orquestra integration | Receive deployment events from Orquestra and annotate metric charts at decision/deploy boundaries |
| 4 | ARIMA/statsmodels: correlation analysis | Implement correlation analysis to detect patterns such as memory spikes after deploys |
| 5 | Notification channels: email and Slack | Add SMTP email and Slack webhook notification channels for alert delivery |
| 6 | Dashboard: capacity planning panel | Build capacity planning panel with forecast visualization and confidence intervals |

---

## Phase 5 — Production Hardening

**Goal**: Operational maturity, complete documentation, and production polish.

| # | Title | Description |
|---|-------|-------------|
| 1 | Multi-agent management | Implement server registry with register/deregister support and metadata (hostname, OS, tags) |
| 2 | Agent: graceful shutdown | Implement graceful shutdown in the Go agent with flush of buffered metrics before exit |
| 3 | Agent: YAML config file | Add YAML configuration file support for sampling rates, Redis URL, batch size — no hardcoded values |
| 4 | Performance: ClickHouse tuning | Tune ClickHouse batch insert performance and add connection pooling in FastAPI |
| 5 | Docker Compose: local dev environment | Create full Docker Compose setup covering Redis, ClickHouse, API, and seeder |
| 6 | Documentation: complete reference | Write complete API reference, agent setup guide, and deployment guide |
| 7 | README: architecture diagram and badges | Add architecture diagram, CI/version badges, and live demo link to README |
