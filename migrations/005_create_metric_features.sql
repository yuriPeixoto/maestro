-- Migration: 005_create_metric_features
-- Description: Create the feature store table for ML pipeline (Phase 3).
-- Pre-computed features derived from raw metrics — used to train and score the Isolation Forest model.
-- Engine: ReplacingMergeTree so the pipeline can safely re-process overlapping time windows;
--         ClickHouse deduplicates rows with the same (server_id, metric_name, timestamp) in background.

CREATE TABLE IF NOT EXISTS maestro.metric_features
(
    server_id        LowCardinality(String),
    metric_name      LowCardinality(String),

    -- UTC timestamp matching the source metric row.
    timestamp        DateTime64(3, 'UTC'),

    -- Raw metric value carried through for reference and model scoring.
    raw_value        Float64,

    -- 5-minute rolling statistics over the raw value series.
    rolling_mean_5m  Float64,
    rolling_std_5m   Float64,

    -- Instantaneous rate of change: (value_t - value_{t-1}) / elapsed_seconds.
    -- Zero for the first data point in any window.
    rate_of_change   Float64,

    -- Cyclic hour-of-day encoding. sin/cos together represent hour as a point
    -- on a unit circle — preserving continuity between 23:59 and 00:00.
    hour_sin         Float64,
    hour_cos         Float64,

    -- Day-of-week (0=Monday … 6=Sunday) and weekend flag.
    day_of_week      UInt8,
    is_weekend       UInt8
)
ENGINE = ReplacingMergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (server_id, metric_name, timestamp)
TTL timestamp + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;
