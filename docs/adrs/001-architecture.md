# ADR-001: System Architecture — Observability Platform (Maestro)

**Status:** Accepted
**Date:** 2026-03-07 (migrated from .txt)

## Context

On-premise infrastructure and distributed application monitoring.
The platform must collect telemetry without impacting the monitored host's resources.

## Decisions

### 1. Ingestion Agent in Go

- **Choice:** Lightweight Go binaries for local metric collection.
- **Motivation:** Raw performance and low memory footprint (CPU/RAM) — the agent must not impact the monitored server.
- **Pattern:** Worker Pool with Buffered Channels and Goroutines.
  - Channels limit the buffer to prevent application stalls.
  - Batching: send events in batches (50 items OR 5s timeout) to reduce connection overhead by ~90%.

### 2. Storage: ClickHouse (Columnar DB)

- **Choice:** ClickHouse as the primary telemetry database.
- **Motivation:** High-performance ingestion and OLAP analytical queries.
- **Table strategy:**
  - Engine: `MergeTree` for high performance.
  - `LowCardinality` for repetitive fields (`host_id`, `tenant_id`) — faster queries, lower memory.
  - Compression: `codec(ZSTD(1))` for text logs — up to 80% disk reduction.
  - Partitioning: by day or month (`toYYYYMM`), optimized for "last 24h" reads.

### 3. Streaming & Decoupling: Redis Streams

- **Choice:** Redis Streams between the Ingestion API and the database.
- **Motivation:** Lower infrastructure overhead vs. Kafka. Ensures events remain queued if ClickHouse oscillates — no data loss.

### 4. Intelligence & API: FastAPI (Python)

- **Choice:** Python/FastAPI for control plane and dashboard backend.
- **Motivation:** Fast development cycle and rich ML ecosystem for future anomaly detection.
- **Alert Engine:** Independent worker process for threshold checks — runs in parallel without blocking the UI.

### 5. Polymorphic JSON Data Contract

- **Structure:** A single contract for metrics and logs.
- **Base fields:** `timestamp`, `host_id`, `tenant_id`, `type`, `payload`, `tags`.
- **Goal:** Unified telemetry in a single table for event correlation (e.g., log error vs. CPU spike at the same instant).

### 6. Notification Channels

| Level | Channel | Use Case |
|-------|---------|----------|
| Operational | Discord / Slack webhooks | Immediate alerts |
| Senior | Telegram Bot API | Private support channel |
| Critical | SMTP / Email | Infrastructure base failures |

## Consequences

- The "heavy lifting" (collection) stays in Go; the "intelligence" (dashboards, alerts, ML) stays in Python.
- Redis Streams acts as a resilience buffer — the system tolerates temporary ClickHouse downtime without data loss.
- Future ML anomaly detection (Scikit-learn, Prophet) plugs into the Python layer without touching the agent.
