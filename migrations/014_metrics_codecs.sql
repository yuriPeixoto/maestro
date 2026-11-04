-- Migration: 014_metrics_codecs
-- Description: Per-column compression codecs for the raw time-series tables. The data does not
--              change, only how it is stored on disk. Chosen by measuring three days of real
--              samples (12 metrics, one server) on ClickHouse 25.5:
--                - DoubleDelta on timestamps, which grow in a fixed step within a series: the
--                  metrics timestamp column went from 1.25 MiB to 4 KiB;
--                - ZSTD on gauge values: smaller than Gorilla on this data (1.56 vs 1.98 MiB);
--                - FPC on the smooth derived floats (rolling std, hour sin/cos), where it beat ZSTD.
--              Whole tables: metrics -48%, anomaly_scores -63%, metric_features -37%.
--              Changing a codec only rewrites metadata: new parts use it at once, existing parts are
--              recompressed as background merges rewrite them. No OPTIMIZE is needed.
-- Run with: clickhouse-client --host <host> --port <port> --user <user> --password <password> --multiquery < migrations/014_metrics_codecs.sql

ALTER TABLE maestro.metrics
    MODIFY COLUMN timestamp DateTime('UTC') CODEC(DoubleDelta, ZSTD(1)),
    MODIFY COLUMN value     Float64         CODEC(ZSTD(1));

ALTER TABLE maestro.metric_features
    MODIFY COLUMN timestamp       DateTime64(3, 'UTC') CODEC(DoubleDelta, ZSTD(1)),
    MODIFY COLUMN raw_value       Float64 CODEC(ZSTD(1)),
    MODIFY COLUMN rolling_mean_5m Float64 CODEC(ZSTD(1)),
    MODIFY COLUMN rolling_std_5m  Float64 CODEC(FPC, ZSTD(1)),
    MODIFY COLUMN rate_of_change  Float64 CODEC(ZSTD(1)),
    MODIFY COLUMN hour_sin        Float64 CODEC(FPC, ZSTD(1)),
    MODIFY COLUMN hour_cos        Float64 CODEC(FPC, ZSTD(1)),
    MODIFY COLUMN day_of_week     UInt8   CODEC(ZSTD(1)),
    MODIFY COLUMN is_weekend      UInt8   CODEC(ZSTD(1));

ALTER TABLE maestro.anomaly_scores
    MODIFY COLUMN timestamp     DateTime64(3, 'UTC') CODEC(DoubleDelta, ZSTD(1)),
    MODIFY COLUMN score         Float64 CODEC(ZSTD(1)),
    MODIFY COLUMN model_version String  CODEC(ZSTD(1));
