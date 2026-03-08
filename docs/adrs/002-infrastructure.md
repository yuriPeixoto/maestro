# ADR-002: Infrastructure & Stack Justification

**Status:** Accepted
**Date:** 2026-03-07 (migrated from .txt)

## Context

This document details the technical rationale for each stack choice and the expansion
potential of the Maestro ecosystem.

## Python: Intelligence & Analysis (The Brain)

### Pandas — Data Manipulation

- **What it is:** High-performance library for data manipulation and analysis.
- **Use case in Maestro:**
  - Trend Analysis reports: Python reads 30 days from ClickHouse; Pandas identifies that memory consumption grows 15% on each Friday deploy.
  - Complex log aggregation that would be too costly in raw SQL.

### Machine Learning — Predictive Alerting

- **What it is:** Algorithms (Scikit-learn, Prophet) that learn patterns from historical data.
- **Use case in Maestro:**
  - Dynamic Thresholds instead of static alerts (`CPU > 90%`).
  - The model learns that traffic spikes at 10 AM are normal, but a 40% spike at 3 AM is an anomaly — triggering a proactive alert before the system fails.

## Go: Performance & Low-Level (The Engine)

### Goroutines — Elite Concurrency

- **What it is:** Lightweight threads managed by the Go runtime — massive simultaneous execution with minimal RAM overhead.
- **Use case in Maestro:**
  - The agent monitors simultaneously: 10 log files, system metrics (CPU/RAM), and database healthchecks.
  - Each task runs in a separate Goroutine — if one log read stalls, CPU monitoring continues unaffected.

### eBPF — Future Expansion (Phase 3+)

- **What it is:** Technology to run safe programs inside the Linux kernel without modifying the OS.
- **Use case in Maestro:**
  - Network monitoring and system calls at kernel level.
  - Observe what each process does (which files it opens, which connections it makes) with near-zero performance impact (zero-overhead observability).

## Role Summary

| Component | Language | Focus |
|-----------|----------|-------|
| Agent | Go | Efficiency — collect raw data (logs/infra) in batches, compress and stream |
| API / Backend | Python (FastAPI) | Intelligence — ingest, orchestrate ClickHouse, Pandas/ML for predictive alerts |
| Storage | ClickHouse | Columnar OLAP — millions of rows in milliseconds |
| Queue | Redis Streams | Decoupling — resilience buffer between agent and storage |
| Frontend | React + Vite + ECharts | Real-time dashboard |

## Consequences

- Clear separation of concerns: Go handles performance-critical collection; Python handles intelligence and analytics.
- ClickHouse chosen over PostgreSQL for columnar OLAP performance on time-series data.
- Redis Streams chosen over Kafka to minimize infrastructure overhead in on-premise environments.
