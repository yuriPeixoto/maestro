-- Migration: 008_create_alert_channels
-- Description: Per-rule notification channels. ReplacingMergeTree allows logical
--              updates (re-insert with higher version to enable/disable a channel).
--              config column stores channel-specific JSON: {"url": "..."} for webhook/slack,
--              {"to": "..."} for email.
-- Run with: clickhouse-client --host <host> --port <port> --user <user> --password <password> --multiquery < migrations/008_create_alert_channels.sql

CREATE TABLE IF NOT EXISTS maestro.alert_channels
(
    channel_id   UUID,
    rule_id      UUID,
    server_id    String,
    channel_type LowCardinality(String),  -- 'webhook', 'email', 'slack'
    config       String,                  -- JSON, channel-specific fields
    enabled      UInt8 DEFAULT 1,
    created_at   DateTime('UTC'),
    version      UInt64                   -- unix ms; higher = newer record wins
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (server_id, rule_id, channel_id)
SETTINGS index_granularity = 8192;
