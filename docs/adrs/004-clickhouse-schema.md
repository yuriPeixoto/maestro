# ADR-004: ClickHouse Schema Design

**Status**: Accepted
**Date**: 2026-03-08
**Deciders**: Yuri Peixoto

---

## Context

Maestro collects time-series metrics from multiple servers at high frequency (CPU every 5s, memory every 15s, disk every 5s). The storage layer must support:

- Fast range queries by server and metric (e.g., "last 30 minutes of CPU for server-A")
- Automatic data expiry after 90 days to cap storage costs
- High write throughput from multiple agents simultaneously
- Low query latency for dashboard rendering

ClickHouse was chosen as the storage engine (see ADR-002). This ADR covers the internal schema design.

---

## Decision

### Table Engine: MergeTree

Use `MergeTree` — ClickHouse's primary engine for append-heavy, analytics-oriented workloads. It supports:

- Efficient batch inserts (data is written to parts and merged in the background)
- Primary key-based filtering that prunes unnecessary data blocks
- TTL expressions at the table level
- No transactions required (agent data is idempotent by design)

ReplacingMergeTree and CollapsingMergeTree were considered but rejected — they add complexity without benefit here since agents do not emit duplicate keys.

### Partitioning: by Month

```sql
PARTITION BY toYYYYMM(timestamp)
```

Partitioning by month ensures that:

- Old data can be dropped by partition (efficient TTL enforcement)
- Queries constrained to recent time windows hit only 1-2 partitions
- Partition count stays manageable (12 per year)

Partitioning by day was considered but would create too many small partitions and increase metadata overhead.

### Sort Key

```sql
ORDER BY (server_id, metric_name, timestamp)
```

This key means ClickHouse can resolve any query of the form "give me metric X for server Y in time range Z" with a narrow read on a contiguous block of data. The `timestamp` at the end enables efficient range scans within a `(server_id, metric_name)` pair.

Putting `timestamp` first was rejected — it would scatter data for any given server+metric across many blocks, making per-server queries expensive.

### LowCardinality for metric_name

```sql
metric_name LowCardinality(String)
```

`metric_name` has a small, bounded set of values (e.g., `cpu_usage_percent`, `memory_used_bytes`, `disk_read_bytes_per_sec`). ClickHouse's `LowCardinality` encoding stores a dictionary instead of repeating the full string per row, reducing storage by approximately 60–80% for this column and improving scan speed.

### 90-Day TTL

```sql
TTL timestamp + INTERVAL 90 DAY
```

Metrics older than 90 days are automatically deleted during ClickHouse's background merge operations. This caps storage without requiring a separate cleanup job.

### Why NOT a Wide Table

A "wide table" design — one column per metric, one row per server per timestamp — was explicitly rejected:

- Adding a new metric requires a schema migration (`ALTER TABLE ADD COLUMN`)
- Sparse data wastes storage (a row has NULL for every metric not collected at that exact tick)
- The query pattern (one metric over time) maps naturally to a narrow tall table, not a wide one
- ClickHouse performs best on tall tables with a well-chosen sort key

### Final Schema

```sql
CREATE TABLE metrics
(
    server_id    String,
    metric_name  LowCardinality(String),
    value        Float64,
    timestamp    DateTime,
    tags         Map(String, String)  -- optional: environment, region, etc.
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (server_id, metric_name, timestamp)
TTL timestamp + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;
```

The `tags` column uses `Map(String, String)` to allow optional per-metric metadata (e.g., disk device name for `disk_read_bytes_per_sec`) without widening the schema. It defaults to an empty map and is not part of the sort key.

---

## Alternatives Considered

| Option | Reason Rejected |
|--------|----------------|
| Wide table (one column per metric) | Schema migrations required for new metrics; sparse storage |
| TimescaleDB (PostgreSQL extension) | Slower on analytical queries vs ClickHouse; no columnar compression |
| InfluxDB | Separate infrastructure; ClickHouse already in the stack |
| Daily partitioning | Too many partitions; metadata overhead |

---

## Consequences

**Positive**:
- Fast range queries on any `(server_id, metric_name)` pair — sublinear data scan
- TTL auto-manages storage without a cron job
- LowCardinality encoding reduces storage significantly for metric names
- New metrics require no schema change — just emit a new `metric_name`

**Negative**:
- Schema cannot be changed lightly — modifying the sort key requires recreating the table
- ClickHouse does not support transactions — partial inserts on crash must be handled by the agent's ring buffer (see Phase 1, Issue 2)
- `Map(String, String)` for tags has limited query performance compared to concrete columns if tags need to be heavily filtered
