from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

import clickhouse_connect

from app.config import settings

logger = logging.getLogger(__name__)

_INSERT_COLUMNS = ["server_id", "metric_name", "value", "timestamp", "tags"]


@dataclass
class MetricRow:
    server_id: str
    metric_name: str
    value: float
    timestamp: datetime
    tags: dict


@dataclass
class DataPoint:
    timestamp: datetime
    value: float


# ── Writer ────────────────────────────────────────────────────────────────────

class ClickHouseWriter:
    """Async batch writer for the metrics table."""

    def __init__(self) -> None:
        self._client = clickhouse_connect.get_async_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_database,
        )

    async def insert_batch(self, rows: list[MetricRow]) -> None:
        if not rows:
            return

        data = [
            [r.server_id, r.metric_name, r.value, r.timestamp, r.tags or {}]
            for r in rows
        ]

        delay = settings.consumer_retry_base_delay
        for attempt in range(1, settings.consumer_retry_max + 1):
            try:
                await self._client.insert("metrics", data=data, column_names=_INSERT_COLUMNS)
                logger.debug("clickhouse: inserted %d rows", len(rows))
                return
            except Exception as exc:
                if attempt == settings.consumer_retry_max:
                    logger.error(
                        "clickhouse: insert failed after %d attempts, dropping %d rows: %s",
                        attempt, len(rows), exc,
                    )
                    return
                logger.warning(
                    "clickhouse: attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt, settings.consumer_retry_max, exc, delay,
                )
                await asyncio.sleep(delay)
                delay *= 2

    async def close(self) -> None:
        await self._client.close()


# ── Reader ────────────────────────────────────────────────────────────────────

class ClickHouseReader:
    """Async reader for dashboard and API metric queries.

    Queries use the sort key (server_id, metric_name, timestamp) so ClickHouse
    can resolve them with a narrow granule scan — no full table scans.
    """

    def __init__(self) -> None:
        self._client = clickhouse_connect.get_async_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_database,
        )

    async def get_metric_names(self, server_id: str) -> list[str]:
        """Return distinct metric names available for a given server."""
        result = await self._client.query(
            "SELECT DISTINCT metric_name"
            " FROM metrics"
            " WHERE server_id = {server_id:String}"
            " ORDER BY metric_name",
            parameters={"server_id": server_id},
        )
        return [row[0] for row in result.result_rows]

    async def get_metric_series(
        self,
        server_id: str,
        metric_name: str,
        minutes: int,
    ) -> list[DataPoint]:
        """Return time-series data points for a server/metric in the last N minutes.

        The WHERE clause on (server_id, metric_name, timestamp) aligns with the
        sort key ORDER BY (server_id, metric_name, timestamp), ensuring ClickHouse
        reads only the relevant data parts.
        """
        result = await self._client.query(
            "SELECT timestamp, value"
            " FROM metrics"
            " WHERE server_id = {server_id:String}"
            "   AND metric_name = {metric_name:String}"
            "   AND timestamp >= now() - INTERVAL {minutes:UInt32} MINUTE"
            " ORDER BY timestamp",
            parameters={
                "server_id": server_id,
                "metric_name": metric_name,
                "minutes": minutes,
            },
        )
        return [DataPoint(timestamp=row[0], value=row[1]) for row in result.result_rows]

    async def close(self) -> None:
        await self._client.close()