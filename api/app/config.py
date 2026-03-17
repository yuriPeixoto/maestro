from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_stream: str = "maestro:metrics"
    redis_consumer_group: str = "maestro-api"
    redis_consumer_name: str = "worker-1"

    # Heartbeat
    heartbeat_stream: str = "maestro:heartbeat"
    heartbeat_consumer_group: str = "maestro-heartbeat"
    heartbeat_consumer_name: str = "heartbeat-worker-1"
    # Redis hash key where last_seen state is stored: field=server_id, value=JSON
    heartbeat_state_key: str = "maestro:server_heartbeats"
    # Seconds without a heartbeat before a server is considered offline
    offline_threshold_seconds: int = 90

    # ClickHouse
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_database: str = "maestro"

    # Consumer tuning
    consumer_batch_size: int = 500
    consumer_flush_interval_ms: int = 5000
    consumer_retry_max: int = 3
    consumer_retry_base_delay: float = 1.0

    model_config = {"env_prefix": "MAESTRO_"}


settings = Settings()