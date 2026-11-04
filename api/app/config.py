from pathlib import Path

from pydantic_settings import BaseSettings

_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_stream: str = "maestro:metrics"
    redis_consumer_group: str = "maestro-api"
    redis_consumer_name: str = "worker-1"

    # Logs
    log_stream: str = "maestro:logs"
    log_consumer_group: str = "maestro-logs"
    log_consumer_name: str = "log-worker-1"

    # Heartbeat
    heartbeat_stream: str = "maestro:heartbeat"
    heartbeat_consumer_group: str = "maestro-heartbeat"
    heartbeat_consumer_name: str = "heartbeat-worker-1"
    heartbeat_state_key: str = "maestro:server_heartbeats"
    offline_threshold_seconds: int = 90
    default_rules_applied_key: str = "maestro:default_rules_applied"  # SET of servers already given default rules

    # Worker: how its tasks are doing, published for the API's /health
    worker_health_key: str = "maestro:worker:health"

    # Installation name shown in the interface; empty hides it
    client_name: str = ""

    # Default limits behind a server's state, in percent
    health_cpu_attention_percent: float = 68.0
    health_cpu_critical_percent: float = 80.0
    health_memory_attention_percent: float = 76.0
    health_memory_critical_percent: float = 90.0
    health_disk_attention_percent: float = 80.0
    health_disk_critical_percent: float = 95.0

    # Agent registry (Redis-backed, no PostgreSQL dependency)
    registry_key: str = "maestro:agents"
    agent_ids_key: str = "maestro:agent_ids"

    # ClickHouse
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "maestro_app"
    clickhouse_password: str = ""
    clickhouse_database: str = "maestro"
    clickhouse_pool_size: int = 10

    # Consumer tuning
    consumer_batch_size: int = 1000
    consumer_flush_interval_ms: int = 5000
    consumer_retry_max: int = 3
    consumer_retry_base_delay: float = 1.0

    # Metric query limits
    metrics_query_default_minutes: int = 30
    metrics_query_max_minutes: int = 1440  # 24 hours; longer windows read the hourly rollup
    metrics_history_max_days: int = 90

    # Auth
    admin_username: str = "admin"
    admin_password_hash: str = ""  # legacy — only used to bootstrap the first user row, see auth_db.init_db()
    jwt_secret: str = ""  # required: the API refuses to start without one, see check_jwt_secret()
    jwt_expire_minutes: int = 1440  # 24 hours
    auth_db_path: str = "data/maestro_auth.db"
    password_reset_token_expire_minutes: int = 30
    frontend_url: str = "http://localhost:5173"  # used to build the link in password-reset emails

    # SMTP (email notifications)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "maestro@localhost"
    smtp_tls: bool = True

    # Telegram notifications. The token stays in the environment; a channel can
    # leave its chat_id empty to use the default one.
    telegram_bot_token: str = ""
    telegram_default_chat_id: str = ""

    # Language of notification texts: "pt-BR" or "en"
    notification_language: str = "pt-BR"

    # Correlation analysis
    correlation_window_before_min: int = 10
    correlation_window_after_min: int = 30

    # Vulnerability scanning (OSV.dev)
    vuln_scan_interval_hours: int = 24
    packages_key: str = "maestro:packages"  # HSET {server_id} -> OS package snapshot written by the agent

    model_config = {"env_prefix": "MAESTRO_", "env_file": str(_ENV_FILE), "env_file_encoding": "utf-8"}


settings = Settings()

# HS256 needs a key at least as long as its 256-bit output (RFC 7518, 3.2).
_JWT_SECRET_MIN_LENGTH = 32
# Defaults that older versions shipped or documented. They are public, so a token
# signed with one can be forged by anyone.
_PUBLIC_JWT_SECRETS = frozenset({"change-me-before-deploy", "dev-secret-change-in-production"})


def check_jwt_secret(secret: str) -> None:
    """Raise when the token secret is missing, short or one of the public defaults."""
    if not secret:
        raise RuntimeError("MAESTRO_JWT_SECRET is not set. Generate one with: openssl rand -hex 32")
    if secret in _PUBLIC_JWT_SECRETS:
        raise RuntimeError("MAESTRO_JWT_SECRET is a published default. Generate one with: openssl rand -hex 32")
    if len(secret) < _JWT_SECRET_MIN_LENGTH:
        raise RuntimeError(
            f"MAESTRO_JWT_SECRET has {len(secret)} characters; use at least {_JWT_SECRET_MIN_LENGTH}"
            " (openssl rand -hex 32)"
        )