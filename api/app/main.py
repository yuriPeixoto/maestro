import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app.alert_evaluator import run_alert_evaluator
from app.alerts import router as alerts_router
from app.auth import get_current_user
from app.auth import router as auth_router
from app.clickhouse import ClickHouseReader, ClickHouseWriter
from app.consumer import run_consumer
from app.heartbeat import run_heartbeat_consumer
from app.log_consumer import run_log_consumer
from app.inventory import router as inventory_router
from app.logs import router as logs_router
from app.metrics import router as metrics_router
from app.security import router as security_router
from app.servers import router as servers_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise shared resources.
    writer = ClickHouseWriter()
    reader = ClickHouseReader()
    await writer.connect()
    await reader.connect()
    app.state.ch_reader = reader
    app.state.ch_writer = writer

    # Start background consumers.
    metrics_task = asyncio.create_task(run_consumer(writer), name="metrics-consumer")
    heartbeat_task = asyncio.create_task(run_heartbeat_consumer(), name="heartbeat-consumer")
    log_task = asyncio.create_task(run_log_consumer(writer), name="log-consumer")
    alert_task = asyncio.create_task(run_alert_evaluator(reader, writer), name="alert-evaluator")
    logger.info("app: metrics, heartbeat, log consumers and alert evaluator started")

    yield

    # Graceful shutdown.
    for task in (metrics_task, heartbeat_task, log_task, alert_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await writer.close()
    await reader.close()
    logger.info("app: all consumers stopped, connections closed")


app = FastAPI(title="Maestro API", lifespan=lifespan)

_protected = [Depends(get_current_user)]

app.include_router(auth_router)
app.include_router(servers_router, dependencies=_protected)
app.include_router(metrics_router, dependencies=_protected)
app.include_router(logs_router, dependencies=_protected)
app.include_router(security_router, dependencies=_protected)
app.include_router(inventory_router, dependencies=_protected)
app.include_router(alerts_router, dependencies=_protected)


@app.get("/")
async def root():
    return {"message": "Maestro API is running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}