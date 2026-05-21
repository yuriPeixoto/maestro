-- Migration: 009_create_server_events
-- Description: Generic timestamped event log per server. Used as input for
--              correlation analysis (e.g. deploy → metric impact). Any producer
--              (CI/CD pipeline, manual entry, Orquestra) can write here via
--              POST /events/{server_id}.
-- Run with: clickhouse-client --host <host> --port <port> --user <user> --password <password> --multiquery < migrations/009_create_server_events.sql

CREATE TABLE IF NOT EXISTS maestro.server_events
(
    event_id    UUID,
    server_id   String,
    event_type  LowCardinality(String),  -- 'deploy', 'restart', 'config_change', etc.
    label       String,                  -- human-readable description
    metadata    String,                  -- JSON, arbitrary key-value context
    occurred_at DateTime('UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (server_id, occurred_at)
TTL occurred_at + INTERVAL 365 DAY
SETTINGS index_granularity = 8192;
