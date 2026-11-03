-- Migration: 011_create_notification_log
-- Description: One row per notification sent to a channel (alert, back to normal or test),
--              with the failure reason when the channel refused it. Feeds the channel screen.
--              rule_id is the nil UUID for a test send, as is event_id.
-- Run with: clickhouse-client --host <host> --port <port> --user <user> --password <password> --multiquery < migrations/011_create_notification_log.sql

CREATE TABLE IF NOT EXISTS maestro.notification_log
(
    sent_at      DateTime('UTC'),
    server_id    String,
    channel_id   UUID,
    channel_type LowCardinality(String),  -- 'webhook', 'email', 'slack', 'telegram'
    rule_id      UUID,
    event_id     UUID,
    kind         LowCardinality(String),  -- 'firing', 'resolved', 'test'
    ok           UInt8,
    error        String                   -- empty when ok; never holds a URL or token
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(sent_at)
ORDER BY (server_id, sent_at)
TTL sent_at + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;
