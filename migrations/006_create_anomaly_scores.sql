-- Migration: 006_create_anomaly_scores
-- Description: Stores per-datapoint anomaly scores produced by the Isolation Forest model.
-- One row per (server_id, metric_name, timestamp) — score in [0, 1] where 1 = most anomalous.
-- Engine: ReplacingMergeTree so re-scoring with a newer model version replaces the old score
--         for the same timestamp without duplicating rows.

CREATE TABLE IF NOT EXISTS maestro.anomaly_scores
(
    server_id     LowCardinality(String),
    metric_name   LowCardinality(String),

    -- UTC timestamp matching the source metric_features row.
    timestamp     DateTime64(3, 'UTC'),

    -- Anomaly score in [0.0, 1.0]. 0 = normal, 1 = most anomalous.
    -- Normalised from IsolationForest.decision_function() using training-set min/max.
    score         Float64,

    -- ISO-8601 UTC string identifying which model run produced this score.
    -- Used to audit score provenance and filter stale scores after retraining.
    model_version String
)
ENGINE = ReplacingMergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (server_id, metric_name, timestamp)
TTL timestamp + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;
