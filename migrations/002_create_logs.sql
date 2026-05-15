CREATE TABLE IF NOT EXISTS maestro.logs
(
    server_id  LowCardinality(String),
    log_file   LowCardinality(String),
    timestamp  DateTime64(3, 'UTC'),
    line       String
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (server_id, log_file, timestamp)
TTL timestamp + INTERVAL 30 DAY
SETTINGS index_granularity = 8192;
