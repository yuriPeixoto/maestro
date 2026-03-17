-- Migration: 001_create_metrics
-- Description: Create the primary metrics table for Maestro time-series storage.
-- Engine: MergeTree (see ADR-004 for full design rationale)
-- Run with: clickhouse-client --host <host> --port <port> --user <user> --password <password> --multiquery < migrations/001_create_metrics.sql

CREATE DATABASE IF NOT EXISTS maestro;

CREATE TABLE IF NOT EXISTS maestro.metrics
(
    -- Server that emitted this metric. Matches the agent's MAESTRO_SERVER_ID (default: hostname).
    server_id   String,

    -- Prometheus-style snake_case metric name (e.g. cpu_usage_percent, disk_read_bytes_per_sec).
    -- LowCardinality encodes a dictionary — ~60-80% storage reduction for low-cardinality strings.
    metric_name LowCardinality(String),

    -- Measured value. Float64 covers all current metric types (percent, bytes, counts).
    value       Float64,

    -- UTC timestamp at the moment of collection. Second-precision is sufficient for 5s+ intervals.
    timestamp   DateTime,

    -- Optional per-metric tags (e.g. device='sda', mount='/var', interface='eth0').
    -- Defaults to an empty map. Not part of the sort key — not suitable for high-cardinality filters.
    tags        Map(String, String)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (server_id, metric_name, timestamp)
TTL timestamp + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;