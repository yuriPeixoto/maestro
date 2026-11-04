-- Migration: 015_create_anomaly_episodes
-- Description: Anomaly episodes: runs of minutes in which a server left its normal range for the
--              hour (seasonal baseline), with what was unusual and what normal would have been.
--              An open episode is rewritten every minute while it lasts; ReplacingMergeTree keeps the
--              latest version per (server_id, started_at), so readers use FINAL.
-- Run with: clickhouse-client --host <host> --port <port> --user <user> --password <password> --multiquery < migrations/015_create_anomaly_episodes.sql

CREATE TABLE IF NOT EXISTS maestro.anomaly_episodes
(
    server_id   String,
    started_at  DateTime('UTC'),
    ended_at    DateTime('UTC'),               -- exclusive: one minute after the last flagged minute
    is_open     UInt8,                         -- 1 while the episode may still grow
    metrics     Array(LowCardinality(String)), -- metrics outside their normal range, worst first
    peak_z      Float64,                       -- largest deviation, in spreads (signed)
    details     String CODEC(ZSTD(1)),         -- JSON list: metric, value, z, normal_low, normal_high, peak_at
    updated_at  DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(started_at)
ORDER BY (server_id, started_at)
TTL started_at + INTERVAL 365 DAY
SETTINGS index_granularity = 8192;
