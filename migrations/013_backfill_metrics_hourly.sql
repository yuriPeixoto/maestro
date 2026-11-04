-- Migration: 013_backfill_metrics_hourly
-- Description: Fills maestro.metrics_hourly with the raw rows that existed before the materialized
--              view of 012 was created. Run it right after 012, and before the raw rows expire
--              (90-day TTL on maestro.metrics): an hour that is gone from the raw table is gone for good.
--
--              The view starts at the first hour it saw (min(hour) in metrics_hourly); everything
--              older comes from here. That first hour is left as the view wrote it, holding only the
--              samples inserted after the view existed, so it is the one partial hour of the rollup.
--              The script is safe to run twice: after the first run min(hour) is the oldest raw hour,
--              and nothing older than it is left to copy. On a fresh installation it copies nothing.
-- Run with: clickhouse-client --host <host> --port <port> --user <user> --password <password> --multiquery < migrations/013_backfill_metrics_hourly.sql

INSERT INTO maestro.metrics_hourly (server_id, metric_name, tags, hour, value_sum, samples, value_min, value_max)
SELECT
    server_id,
    metric_name,
    tags,
    toStartOfHour(timestamp) AS hour,
    sum(value),
    count(),
    min(value),
    max(value)
FROM maestro.metrics
WHERE timestamp < (
    -- An empty rollup means the view has not seen an insert yet: every raw row is older than it.
    SELECT if(count() = 0, now(), min(hour)) FROM maestro.metrics_hourly
)
GROUP BY server_id, metric_name, tags, hour;
