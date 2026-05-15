from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

import clickhouse_connect

from app.config import settings

logger = logging.getLogger(__name__)

_INSERT_COLUMNS = ["server_id", "metric_name", "value", "timestamp", "tags"]
_LOG_INSERT_COLUMNS = ["server_id", "log_file", "timestamp", "line"]


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


@dataclass
class LogRow:
    server_id: str
    log_file: str
    timestamp: datetime
    line: str


@dataclass
class SshStats:
    attempts_1h: int
    attempts_24h: int
    unique_ips_24h: int
    top_target: str | None


# ── Writer ────────────────────────────────────────────────────────────────────

class ClickHouseWriter:
    """Async batch writer for the metrics table."""

    def __init__(self) -> None:
        self._client = None

    async def connect(self) -> None:
        self._client = await clickhouse_connect.get_async_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_database,
        )

    async def insert_log_batch(self, rows: list[LogRow]) -> None:
        if not rows:
            return
        data = [[r.server_id, r.log_file, r.timestamp, r.line] for r in rows]
        delay = settings.consumer_retry_base_delay
        for attempt in range(1, settings.consumer_retry_max + 1):
            try:
                await self._client.insert("logs", data=data, column_names=_LOG_INSERT_COLUMNS)
                logger.debug("clickhouse: inserted %d log rows", len(rows))
                return
            except Exception as exc:
                if attempt == settings.consumer_retry_max:
                    logger.error(
                        "clickhouse: log insert failed after %d attempts, dropping %d rows: %s",
                        attempt, len(rows), exc,
                    )
                    return
                logger.warning("clickhouse: log attempt %d/%d failed: %s — retrying in %.1fs",
                               attempt, settings.consumer_retry_max, exc, delay)
                await asyncio.sleep(delay)
                delay *= 2

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
        if self._client is not None:
            await self._client.close()


# ── Reader ────────────────────────────────────────────────────────────────────

class ClickHouseReader:
    """Async reader for dashboard and API metric queries.

    Queries use the sort key (server_id, metric_name, timestamp) so ClickHouse
    can resolve them with a narrow granule scan — no full table scans.
    """

    def __init__(self) -> None:
        self._client = None

    async def connect(self) -> None:
        self._client = await clickhouse_connect.get_async_client(
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

    async def get_log_history(self, server_id: str, log_file: str, lines: int) -> list[LogRow]:
        result = await self._client.query(
            "SELECT server_id, log_file, timestamp, line"
            " FROM logs"
            " WHERE server_id = {server_id:String}"
            "   AND log_file = {log_file:String}"
            " ORDER BY timestamp DESC"
            " LIMIT {lines:UInt32}",
            parameters={"server_id": server_id, "log_file": log_file, "lines": lines},
        )
        rows = [LogRow(server_id=r[0], log_file=r[1], timestamp=r[2], line=r[3])
                for r in reversed(result.result_rows)]
        return rows

    async def get_logs_since(self, server_id: str, log_file: str, since: datetime) -> list[LogRow]:
        result = await self._client.query(
            "SELECT server_id, log_file, timestamp, line"
            " FROM logs"
            " WHERE server_id = {server_id:String}"
            "   AND log_file = {log_file:String}"
            "   AND timestamp > {since:DateTime64(3)}"
            " ORDER BY timestamp",
            parameters={"server_id": server_id, "log_file": log_file, "since": since},
        )
        return [LogRow(server_id=r[0], log_file=r[1], timestamp=r[2], line=r[3])
                for r in result.result_rows]

    async def get_ssh_stats(self, server_id: str) -> SshStats:
        q_1h, q_24h, q_ips, q_top = await asyncio.gather(
            self._client.query(
                "SELECT count() FROM logs"
                " WHERE server_id = {s:String} AND log_file = 'auth.log'"
                "   AND timestamp >= now() - INTERVAL 1 HOUR"
                "   AND match(line, 'Failed password|Invalid user')",
                parameters={"s": server_id},
            ),
            self._client.query(
                "SELECT count() FROM logs"
                " WHERE server_id = {s:String} AND log_file = 'auth.log'"
                "   AND timestamp >= now() - INTERVAL 24 HOUR"
                "   AND match(line, 'Failed password|Invalid user')",
                parameters={"s": server_id},
            ),
            self._client.query(
                "SELECT count(DISTINCT extract(line, 'from (\\\\S+) port')) FROM logs"
                " WHERE server_id = {s:String} AND log_file = 'auth.log'"
                "   AND timestamp >= now() - INTERVAL 24 HOUR"
                "   AND match(line, 'Failed password|Invalid user')",
                parameters={"s": server_id},
            ),
            self._client.query(
                "SELECT extract(line, 'for (?:invalid user )?(\\\\S+) from') AS u, count() AS cnt"
                " FROM logs"
                " WHERE server_id = {s:String} AND log_file = 'auth.log'"
                "   AND timestamp >= now() - INTERVAL 24 HOUR"
                "   AND match(line, 'Failed password|Invalid user')"
                " GROUP BY u ORDER BY cnt DESC LIMIT 1",
                parameters={"s": server_id},
            ),
        )
        return SshStats(
            attempts_1h=q_1h.result_rows[0][0] if q_1h.result_rows else 0,
            attempts_24h=q_24h.result_rows[0][0] if q_24h.result_rows else 0,
            unique_ips_24h=q_ips.result_rows[0][0] if q_ips.result_rows else 0,
            top_target=q_top.result_rows[0][0] if q_top.result_rows else None,
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()