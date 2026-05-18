-- Migration: 003_create_alert_rules
-- Description: Stores configurable static threshold rules for the alerting engine.
-- ReplacingMergeTree allows logical updates by inserting a new row with higher version.
-- Run with: clickhouse-client --host <host> --port <port> --user <user> --password <password> --multiquery < migrations/003_create_alert_rules.sql

CREATE TABLE IF NOT EXISTS maestro.alert_rules
(
    rule_id          UUID,
    server_id        String,
    metric_name      LowCardinality(String),
    operator         String,                    -- '>', '<', '>=', '<='
    threshold        Float64,
    severity         LowCardinality(String),    -- 'warning', 'critical'
    cooldown_minutes UInt32,
    enabled          UInt8,
    created_at       DateTime('UTC'),
    version          UInt64                     -- unix ms; higher = newer record wins
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (server_id, rule_id)
SETTINGS index_granularity = 8192;
