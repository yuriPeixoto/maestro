-- Migration: 012_create_metrics_hourly
-- Description: Hourly rollup of maestro.metrics, fed by a materialized view on every insert.
--              One row per (server, metric, tag set, hour) holds sum, count, min and max, so the
--              hourly average is sum(value_sum) / sum(samples). It is ~500 times smaller than the
--              raw table and outlives its 90-day TTL: long charts and the capacity forecast read it.
--              Raw data that is already in metrics is not covered by the view; on an existing
--              installation 013_backfill_metrics_hourly.sql fills it from the raw rows.
-- Engine: AggregatingMergeTree. Rows with the same sorting key are merged in the background, so
--         readers must still aggregate (GROUP BY) instead of trusting one row per hour.
-- Run with: clickhouse-client --host <host> --port <port> --user <user> --password <password> --multiquery < migrations/012_create_metrics_hourly.sql

CREATE TABLE IF NOT EXISTS maestro.metrics_hourly
(
    server_id   String,
    metric_name LowCardinality(String),
    -- Same tag set as the raw rows (device, mount, interface). Kept in the key so that one
    -- device's hours never merge into another's.
    tags        Map(String, String),
    hour        DateTime('UTC') CODEC(Delta, ZSTD(1)),

    value_sum   SimpleAggregateFunction(sum, Float64) CODEC(ZSTD(1)),
    samples     SimpleAggregateFunction(sum, UInt64)  CODEC(T64, ZSTD(1)),
    value_min   SimpleAggregateFunction(min, Float64) CODEC(ZSTD(1)),
    value_max   SimpleAggregateFunction(max, Float64) CODEC(ZSTD(1))
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(hour)
ORDER BY (server_id, metric_name, hour, tags)
TTL hour + INTERVAL 730 DAY
SETTINGS index_granularity = 8192;

CREATE MATERIALIZED VIEW IF NOT EXISTS maestro.metrics_hourly_mv
TO maestro.metrics_hourly
AS
SELECT
    server_id,
    metric_name,
    tags,
    toStartOfHour(timestamp) AS hour,
    sum(value)               AS value_sum,
    count()                  AS samples,
    min(value)               AS value_min,
    max(value)               AS value_max
FROM maestro.metrics
GROUP BY server_id, metric_name, tags, hour;
