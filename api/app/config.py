from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_stream: str = "maestro:metrics"
    redis_consumer_group: str = "maestro-api"
    redis_consumer_name: str = "worker-1"

    # ClickHouse
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_database: str = "maestro"

    # Consumer tuning
    consumer_batch_size: int = 500       # max rows per ClickHouse insert
    consumer_flush_interval_ms: int = 5000  # XREADGROUP block timeout (ms)
    consumer_retry_max: int = 3          # ClickHouse insert retry attempts
    consumer_retry_base_delay: float = 1.0  # seconds (doubles on each retry)

    model_config = {"env_prefix": "MAESTRO_"}


settings = Settings()