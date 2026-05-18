-- Migration: 004_create_alert_events
-- Description: Append-only log of alert state transitions (FIRING / RESOLVED).
-- Each row is a discrete event; the full history is preserved for the dashboard.
-- Run with: clickhouse-client --host <host> --port <port> --user <user> --password <password> --multiquery < migrations/004_create_alert_events.sql

CREATE TABLE IF NOT EXISTS maestro.alert_events
(
    event_id     UUID,
    rule_id      UUID,
    server_id    String,
    metric_name  LowCardinality(String),
    value        Float64,
    threshold    Float64,
    severity     LowCardinality(String),  -- 'warning', 'critical'
    state        LowCardinality(String),  -- 'FIRING', 'RESOLVED'
    triggered_at DateTime('UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(triggered_at)
ORDER BY (server_id, triggered_at)
TTL triggered_at + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;
