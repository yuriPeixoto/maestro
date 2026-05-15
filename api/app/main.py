import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clickhouse import ClickHouseReader, ClickHouseWriter
from app.consumer import run_consumer
from app.heartbeat import run_heartbeat_consumer
from app.log_consumer import run_log_consumer
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

    # Start background consumers.
    metrics_task = asyncio.create_task(run_consumer(writer), name="metrics-consumer")
    heartbeat_task = asyncio.create_task(run_heartbeat_consumer(), name="heartbeat-consumer")
    log_task = asyncio.create_task(run_log_consumer(writer), name="log-consumer")
    logger.info("app: metrics, heartbeat and log consumers started")

    yield

    # Graceful shutdown.
    for task in (metrics_task, heartbeat_task, log_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await writer.close()
    await reader.close()
    logger.info("app: all consumers stopped, connections closed")


app = FastAPI(title="Maestro API", lifespan=lifespan)

app.include_router(servers_router)
app.include_router(metrics_router)
app.include_router(logs_router)
app.include_router(security_router)


@app.get("/")
async def root():
    return {"message": "Maestro API is running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}