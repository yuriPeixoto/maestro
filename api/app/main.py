import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from pathlib import Path

from app.alert_evaluator import run_alert_evaluator
from app.analysis import router as analysis_router
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
from app.alerts import router as alerts_router
from app.auth import get_current_user
from app.auth import router as auth_router
from app.clickhouse import ClickHouseReader, ClickHouseWriter, create_client
from app.consumer import run_consumer
from app.forecasts import router as forecasts_router
from app.heartbeat import run_heartbeat_consumer
from app.log_consumer import run_log_consumer
from app.inventory import router as inventory_router
from app.logs import router as logs_router
from app.metrics import router as metrics_router
from app.security import router as security_router
from app.servers import router as servers_router
from app.vulnerabilities import router as vuln_router, run_vulnerability_scanner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Single shared ClickHouse client — Writer and Reader reuse the same connection pool.
    ch_client = await create_client()
    writer = ClickHouseWriter(ch_client)
    reader = ClickHouseReader(ch_client)
    app.state.ch_reader = reader
    app.state.ch_writer = writer

    # Shared Redis client for vuln cache and DB connection snapshots.
    import redis.asyncio as aioredis
    vuln_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    app.state.vuln_redis = vuln_redis

    # Initialise ML model store and load any persisted models from disk.
    store = ModelStore(Path(settings.ml_models_dir))
    store.load_all()
    app.state.model_store = store

    # Initialise River online detector and load persisted state.
    river = RiverDetector(Path(settings.ml_models_dir))
    river.load_all()
    app.state.river_detector = river

    # Start background consumers.
    metrics_task = asyncio.create_task(run_consumer(writer), name="metrics-consumer")
    heartbeat_task = asyncio.create_task(run_heartbeat_consumer(), name="heartbeat-consumer")
    log_task = asyncio.create_task(run_log_consumer(writer), name="log-consumer")
    alert_task = asyncio.create_task(run_alert_evaluator(reader, writer), name="alert-evaluator")
    feature_task = asyncio.create_task(run_feature_pipeline(reader, writer), name="feature-pipeline")
    detector_task = asyncio.create_task(run_anomaly_detector(reader, writer, store), name="anomaly-detector")
    river_task = asyncio.create_task(run_river_detector(reader, writer, river), name="river-detector")
    forecast_task = asyncio.create_task(run_forecast_scheduler(reader), name="forecast-scheduler")
    correlation_task = asyncio.create_task(run_correlation_analyzer(reader, writer), name="correlation-analyzer")
    vuln_task = asyncio.create_task(run_vulnerability_scanner(), name="vuln-scanner")
    logger.info("app: all consumers, evaluator, feature pipeline, IF/River detectors, forecast scheduler, correlation analyzer and vulnerability scanner started")

    yield

    # Graceful shutdown.
    for task in (metrics_task, heartbeat_task, log_task, alert_task, feature_task, detector_task, river_task, forecast_task, correlation_task, vuln_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await ch_client.close()
    await vuln_redis.aclose()
    logger.info("app: all consumers stopped, ClickHouse connection closed")


app = FastAPI(title="Maestro API", lifespan=lifespan)

_protected = [Depends(get_current_user)]

app.include_router(auth_router)
app.include_router(servers_router, dependencies=_protected)
app.include_router(metrics_router, dependencies=_protected)
app.include_router(logs_router, dependencies=_protected)
app.include_router(security_router, dependencies=_protected)
app.include_router(inventory_router, dependencies=_protected)
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


@app.get("/health")
async def health():
    return {"status": "healthy"}