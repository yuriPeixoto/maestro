-- Migration: 010_create_correlation_results
-- Description: Cache of correlation analysis results per server/event_type/metric.
--              ReplacingMergeTree keeps the latest run result; the background worker
--              re-inserts on each nightly run, overwriting stale data.
-- Run with: clickhouse-client --host <host> --port <port> --user <user> --password <password> --multiquery < migrations/010_create_correlation_results.sql

CREATE TABLE IF NOT EXISTS maestro.correlation_results
(
    server_id        String,
    event_type       LowCardinality(String),
    metric_name      LowCardinality(String),
    sample_count     UInt32,                -- number of events used in analysis
    avg_delta        Float64,               -- mean metric change after event
    avg_delta_pct    Float64,               -- mean % change relative to pre-event baseline
    p_value          Float64,               -- one-sample t-test p-value (significance)
    window_before_m  UInt16,                -- minutes of baseline window used
    window_after_m   UInt16,                -- minutes of impact window used
    computed_at      DateTime('UTC'),
    version          UInt64                 -- unix ms; higher = newer record wins
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (server_id, event_type, metric_name)
SETTINGS index_granularity = 8192;
