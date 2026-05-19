from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import clickhouse_connect

from app.config import settings

logger = logging.getLogger(__name__)

_INSERT_COLUMNS = ["server_id", "metric_name", "value", "timestamp", "tags"]
_LOG_INSERT_COLUMNS = ["server_id", "log_file", "timestamp", "line"]
_RULE_INSERT_COLUMNS = ["rule_id", "server_id", "metric_name", "operator", "threshold",
                        "severity", "cooldown_minutes", "enabled", "created_at", "version"]
_EVENT_INSERT_COLUMNS = ["event_id", "rule_id", "server_id", "metric_name",
                         "value", "threshold", "severity", "state", "triggered_at"]
_FEATURE_INSERT_COLUMNS = [
    "server_id", "metric_name", "timestamp", "raw_value",
    "rolling_mean_5m", "rolling_std_5m", "rate_of_change",
    "hour_sin", "hour_cos", "day_of_week", "is_weekend",
]
_SCORE_INSERT_COLUMNS = ["server_id", "metric_name", "timestamp", "score", "model_version"]


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
class AlertRule:
    rule_id: UUID
    server_id: str
    metric_name: str
    operator: str
    threshold: float
    severity: str
    cooldown_minutes: int
    enabled: bool
    created_at: datetime


@dataclass
class AlertEvent:
    event_id: UUID
    rule_id: UUID
    server_id: str
    metric_name: str
    value: float
    threshold: float
    severity: str
    state: str
    triggered_at: datetime


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

    async def insert_alert_rule(self, rule: AlertRule) -> None:
        import time as _time
        data = [[
            rule.rule_id, rule.server_id, rule.metric_name, rule.operator,
            rule.threshold, rule.severity, rule.cooldown_minutes,
            int(rule.enabled), rule.created_at,
            int(_time.time() * 1000),
        ]]
        await self._client.insert("alert_rules", data=data, column_names=_RULE_INSERT_COLUMNS)

    async def insert_feature_batch(self, rows: list) -> None:
        """Bulk-insert pre-computed feature rows into metric_features."""
        if not rows:
            return
        from app.feature_engineering import FeatureRow  # local import avoids circular dep
        data = [
            [
                r.server_id, r.metric_name, r.timestamp, r.raw_value,
                r.rolling_mean_5m, r.rolling_std_5m, r.rate_of_change,
                r.hour_sin, r.hour_cos, r.day_of_week, r.is_weekend,
            ]
            for r in rows
        ]
        delay = self._retry_base_delay if hasattr(self, "_retry_base_delay") else 1.0
        for attempt in range(1, 4):
            try:
                await self._client.insert(
                    "metric_features", data=data, column_names=_FEATURE_INSERT_COLUMNS
                )
                logger.debug("clickhouse: inserted %d feature rows", len(rows))
                return
            except Exception as exc:
                if attempt == 3:
                    logger.error("clickhouse: feature insert failed after 3 attempts: %s", exc)
                    return
                logger.warning("clickhouse: feature insert attempt %d/3: %s — retrying", attempt, exc)
                await asyncio.sleep(delay * (2 ** (attempt - 1)))

    async def insert_alert_event(self, event: AlertEvent) -> None:
        data = [[
            event.event_id, event.rule_id, event.server_id, event.metric_name,
            event.value, event.threshold, event.severity, event.state, event.triggered_at,
        ]]
        await self._client.insert("alert_events", data=data, column_names=_EVENT_INSERT_COLUMNS)

    async def insert_anomaly_scores(
        self,
        server_id: str,
        metric_name: str,
        timestamps: list,
        scores: list[float],
        model_version: str,
    ) -> None:
        """Bulk-insert anomaly scores produced by the Isolation Forest model."""
        if not timestamps:
            return
        data = [
            [server_id, metric_name, ts, score, model_version]
            for ts, score in zip(timestamps, scores)
        ]
        delay = 1.0
        for attempt in range(1, 4):
            try:
                await self._client.insert(
                    "anomaly_scores", data=data, column_names=_SCORE_INSERT_COLUMNS
                )
                logger.debug("clickhouse: inserted %d anomaly scores", len(data))
                return
            except Exception as exc:
                if attempt == 3:
                    logger.error("clickhouse: anomaly score insert failed after 3 attempts: %s", exc)
                    return
                logger.warning("clickhouse: score insert attempt %d/3: %s — retrying", attempt, exc)
                await asyncio.sleep(delay * (2 ** (attempt - 1)))

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

    async def get_alert_rules(self, server_id: str) -> list[AlertRule]:
        result = await self._client.query(
            "SELECT rule_id, server_id, metric_name, operator, threshold,"
            "       severity, cooldown_minutes, enabled, created_at"
            " FROM alert_rules FINAL"
            " WHERE server_id = {server_id:String} AND enabled = 1"
            " ORDER BY created_at",
            parameters={"server_id": server_id},
        )
        return [
            AlertRule(
                rule_id=r[0], server_id=r[1], metric_name=r[2], operator=r[3],
                threshold=r[4], severity=r[5], cooldown_minutes=r[6],
                enabled=bool(r[7]), created_at=r[8],
            )
            for r in result.result_rows
        ]

    async def get_alert_events(self, server_id: str, limit: int = 100) -> list[AlertEvent]:
        result = await self._client.query(
            "SELECT event_id, rule_id, server_id, metric_name, value, threshold,"
            "       severity, state, triggered_at"
            " FROM alert_events"
            " WHERE server_id = {server_id:String}"
            " ORDER BY triggered_at DESC"
            " LIMIT {limit:UInt32}",
            parameters={"server_id": server_id, "limit": limit},
        )
        return [
            AlertEvent(
                event_id=r[0], rule_id=r[1], server_id=r[2], metric_name=r[3],
                value=r[4], threshold=r[5], severity=r[6], state=r[7], triggered_at=r[8],
            )
            for r in result.result_rows
        ]

    async def get_latest_metric_value(self, server_id: str, metric_name: str) -> float | None:
        result = await self._client.query(
            "SELECT MAX(value) FROM metrics"
            " WHERE server_id = {server_id:String}"
            "   AND metric_name = {metric_name:String}"
            "   AND timestamp >= now() - INTERVAL 5 MINUTE",
            parameters={"server_id": server_id, "metric_name": metric_name},
        )
        if not result.result_rows or result.result_rows[0][0] is None:
            return None
        return float(result.result_rows[0][0])

    # ── Feature engineering support ───────────────────────────────────────────

    async def get_known_server_ids(self) -> list[str]:
        """Return all server_ids that have at least one metric row."""
        result = await self._client.query(
            "SELECT DISTINCT server_id FROM metrics ORDER BY server_id",
        )
        return [row[0] for row in result.result_rows]

    async def get_metrics_range(
        self,
        server_id: str,
        metric_name: str,
        since: datetime,
    ) -> list[tuple[datetime, float]]:
        """Return (timestamp, value) pairs for a server/metric since a given UTC datetime."""
        result = await self._client.query(
            "SELECT timestamp, value"
            " FROM metrics"
            " WHERE server_id = {server_id:String}"
            "   AND metric_name = {metric_name:String}"
            "   AND timestamp >= {since:DateTime64(3)}"
            " ORDER BY timestamp",
            parameters={"server_id": server_id, "metric_name": metric_name, "since": since},
        )
        return [(row[0], float(row[1])) for row in result.result_rows]

    async def get_feature_watermark(self, server_id: str, metric_name: str) -> datetime | None:
        """Return the latest timestamp already stored in metric_features for this pair, or None."""
        result = await self._client.query(
            "SELECT MAX(timestamp)"
            " FROM metric_features"
            " WHERE server_id = {server_id:String}"
            "   AND metric_name = {metric_name:String}",
            parameters={"server_id": server_id, "metric_name": metric_name},
        )
        if not result.result_rows or result.result_rows[0][0] is None:
            return None
        ts = result.result_rows[0][0]
        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts

    async def get_features_for_training(
        self,
        server_id: str,
        metric_name: str,
    ):
        """Return a pandas DataFrame of all metric_features rows for model training.

        Fetches all available history (up to 90-day TTL). Returns None if pandas
        is not importable or if no rows are found.
        """
        try:
            import pandas as pd
        except ImportError:
            logger.error("clickhouse: pandas not installed — cannot fetch training features")
            return None

        result = await self._client.query(
            "SELECT timestamp, raw_value,"
            "       rolling_mean_5m, rolling_std_5m, rate_of_change,"
            "       hour_sin, hour_cos, day_of_week, is_weekend"
            " FROM metric_features"
            " WHERE server_id = {server_id:String}"
            "   AND metric_name = {metric_name:String}"
            " ORDER BY timestamp",
            parameters={"server_id": server_id, "metric_name": metric_name},
        )
        if not result.result_rows:
            return None

        cols = [
            "timestamp", "raw_value",
            "rolling_mean_5m", "rolling_std_5m", "rate_of_change",
            "hour_sin", "hour_cos", "day_of_week", "is_weekend",
        ]
        df = pd.DataFrame(result.result_rows, columns=cols)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    async def get_anomaly_scores(
        self,
        server_id: str,
        metric_name: str,
        minutes: int,
    ) -> list[tuple]:
        """Return (timestamp, score) pairs for the last N minutes."""
        result = await self._client.query(
            "SELECT timestamp, score"
            " FROM anomaly_scores FINAL"
            " WHERE server_id = {server_id:String}"
            "   AND metric_name = {metric_name:String}"
            "   AND timestamp >= now() - INTERVAL {minutes:UInt32} MINUTE"
            " ORDER BY timestamp",
            parameters={"server_id": server_id, "metric_name": metric_name, "minutes": minutes},
        )
        return [(row[0], float(row[1])) for row in result.result_rows]

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()