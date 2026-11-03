import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from pathlib import Path

from app.alert_evaluator import run_alert_evaluator
from app.analysis import router as analysis_router
from app.auth_db import init_db as init_auth_db
from app.config import settings
from app.correlation_analyzer import run_correlation_analyzer
from app.db_connections import router as db_connections_router
from app.events import router as events_router
from app.registry import router as registry_router
from app.feature_engineering import run_feature_pipeline
from app.forecast_scheduler import run_forecast_scheduler
from app.ml.anomaly_detector import run_anomaly_detector
from app.ml.model_store import ModelStore
from app.ml.river_detector import RiverDetector, run_river_detector
from app.alert_channels import router as alert_channels_router
from app.alerts import router as alerts_router
from app.auth import require_active_user
from app.auth import router as auth_router
from app.clickhouse import ClickHouseReader, ClickHouseWriter, create_client
from app.consumer import run_consumer
from app.forecasts import router as forecasts_router
from app.heartbeat import run_heartbeat_consumer
from app.log_consumer import run_log_consumer
from app.inventory import router as inventory_router
from app.logs import router as logs_router
from app.meta import router as meta_router
from app.metrics import router as metrics_router
from app.security import router as security_router
from app.servers import router as servers_router
from app.users import router as users_router
from app.vulnerabilities import router as vuln_router, run_vulnerability_scanner
from app.alert_evaluator import EVAL_INTERVAL_SECONDS
from app.health import router as health_router
from app.task_health import TaskRegistry, supervise

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
# httpx logs every request URL at INFO, and a Telegram URL holds the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)

# A consumer beats at least once per blocking read (5–10 s); two minutes without
# one means its inserts keep failing. The evaluator gets five of its cycles.
_CONSUMER_STALE_SECONDS = 120
_EVALUATOR_STALE_SECONDS = EVAL_INTERVAL_SECONDS * 5


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auth store — creates the SQLite schema and bootstraps one user from the
    # legacy admin settings on a fresh install (see auth_db.init_db).
    await init_auth_db()

    # Single shared ClickHouse client — Writer and Reader reuse the same connection pool.
    ch_client = await create_client()
    writer = ClickHouseWriter(ch_client)
    reader = ClickHouseReader(ch_client)
    app.state.ch_reader = reader
    app.state.ch_writer = writer

    # Shared Redis client for vuln cache and DB connection snapshots.
    import redis.asyncio as aioredis
    vuln_redis = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
    app.state.vuln_redis = vuln_redis

    # Initialise ML model store and load any persisted models from disk.
    store = ModelStore(Path(settings.ml_models_dir))
    store.load_all()
    app.state.model_store = store

    # Initialise River online detector and load persisted state.
    river = RiverDetector(Path(settings.ml_models_dir))
    river.load_all()
    app.state.river_detector = river

    # Background tasks, each restarted when it stops. The watched ones must beat
    # within their limit or /health reports them stale.
    registry = TaskRegistry()
    app.state.task_registry = registry
    app.state.ch_client = ch_client
    app.state.started_at = time.monotonic()

    def watched(name: str, stale_after: float, run):
        registry.register(name, stale_after_seconds=stale_after)
        return name, lambda: run(registry.beater(name))

    def unwatched(name: str, run):
        registry.register(name)
        return name, run

    task_specs = [
        watched("metrics-consumer", _CONSUMER_STALE_SECONDS, lambda beat: run_consumer(writer, beat)),
        watched("heartbeat-consumer", _CONSUMER_STALE_SECONDS, run_heartbeat_consumer),
        watched("log-consumer", _CONSUMER_STALE_SECONDS, lambda beat: run_log_consumer(writer, beat)),
        watched("alert-evaluator", _EVALUATOR_STALE_SECONDS, lambda beat: run_alert_evaluator(reader, writer, beat)),
        unwatched("feature-pipeline", lambda: run_feature_pipeline(reader, writer)),
        unwatched("anomaly-detector", lambda: run_anomaly_detector(reader, writer, store)),
        unwatched("river-detector", lambda: run_river_detector(reader, writer, river)),
        unwatched("forecast-scheduler", lambda: run_forecast_scheduler(reader)),
        unwatched("correlation-analyzer", lambda: run_correlation_analyzer(reader, writer)),
        unwatched("vuln-scanner", run_vulnerability_scanner),
    ]
    tasks = [asyncio.create_task(supervise(registry, name, run), name=name) for name, run in task_specs]
    logger.info("app: %d supervised background tasks started", len(tasks))

    yield

    # Graceful shutdown.
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    await ch_client.close()
    await vuln_redis.aclose()
    logger.info("app: all consumers stopped, ClickHouse connection closed")


app = FastAPI(title="Maestro API", lifespan=lifespan)

_protected = [Depends(require_active_user)]

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(meta_router, dependencies=_protected)
app.include_router(users_router, dependencies=_protected)
app.include_router(servers_router, dependencies=_protected)
app.include_router(metrics_router, dependencies=_protected)
app.include_router(logs_router, dependencies=_protected)
app.include_router(security_router, dependencies=_protected)
app.include_router(inventory_router, dependencies=_protected)
app.include_router(alert_channels_router, dependencies=_protected)
app.include_router(alerts_router, dependencies=_protected)
app.include_router(forecasts_router, dependencies=_protected)
app.include_router(events_router, dependencies=_protected)
app.include_router(analysis_router, dependencies=_protected)
app.include_router(registry_router, dependencies=_protected)
app.include_router(vuln_router, dependencies=_protected)
app.include_router(db_connections_router, dependencies=_protected)


@app.get("/")
async def root():
    return {"message": "Maestro API is running"}