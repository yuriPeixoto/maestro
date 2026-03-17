import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clickhouse import ClickHouseWriter
from app.consumer import run_consumer
from app.heartbeat import run_heartbeat_consumer
from app.servers import router as servers_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    writer = ClickHouseWriter()

    metrics_task = asyncio.create_task(run_consumer(writer), name="metrics-consumer")
    heartbeat_task = asyncio.create_task(run_heartbeat_consumer(), name="heartbeat-consumer")

    logger.info("app: metrics consumer and heartbeat consumer started")

    yield

    for task in (metrics_task, heartbeat_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await writer.close()
    logger.info("app: all consumers stopped")


app = FastAPI(title="Maestro API", lifespan=lifespan)

app.include_router(servers_router)


@app.get("/")
async def root():
    return {"message": "Maestro API is running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}