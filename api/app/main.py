import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clickhouse import ClickHouseWriter
from app.consumer import run_consumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the Redis Streams consumer on startup; cancel it on shutdown."""
    writer = ClickHouseWriter()
    task = asyncio.create_task(run_consumer(writer), name="redis-consumer")
    logger.info("app: Redis Streams consumer started")

    yield  # application runs here

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await writer.close()
    logger.info("app: consumer stopped, ClickHouse connection closed")


app = FastAPI(title="Maestro API", lifespan=lifespan)


@app.get("/")
async def root():
    return {"message": "Maestro API is running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}