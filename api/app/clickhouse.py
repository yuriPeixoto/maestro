import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

import clickhouse_connect

from app.config import settings

logger = logging.getLogger(__name__)

# Column order must match the CREATE TABLE in migrations/001_create_metrics.sql.
_COLUMNS = ["server_id", "metric_name", "value", "timestamp", "tags"]


@dataclass
class MetricRow:
    server_id: str
    metric_name: str
    value: float
    timestamp: datetime
    tags: dict


class ClickHouseWriter:
    """Async wrapper around clickhouse-connect for batch metric inserts."""

    def __init__(self) -> None:
        self._client = clickhouse_connect.get_async_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_database,
        )

    async def insert_batch(self, rows: list[MetricRow]) -> None:
        """Insert a batch of metric rows into ClickHouse with exponential backoff retry.

        If all retry attempts fail, the batch is logged and dropped — the consumer
        will still XACK those messages so the stream does not grow unboundedly.
        """
        if not rows:
            return

        data = [
            [r.server_id, r.metric_name, r.value, r.timestamp, r.tags or {}]
            for r in rows
        ]

        delay = settings.consumer_retry_base_delay
        for attempt in range(1, settings.consumer_retry_max + 1):
            try:
                await self._client.insert(
                    "metrics",
                    data=data,
                    column_names=_COLUMNS,
                )
                logger.debug("clickhouse: inserted %d rows", len(rows))
                return
            except Exception as exc:
                if attempt == settings.consumer_retry_max:
                    logger.error(
                        "clickhouse: insert failed after %d attempts, dropping %d rows: %s",
                        attempt,
                        len(rows),
                        exc,
                    )
                    return
                logger.warning(
                    "clickhouse: insert attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt,
                    settings.consumer_retry_max,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                delay *= 2

    async def close(self) -> None:
        await self._client.close()