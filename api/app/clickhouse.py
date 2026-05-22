from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import clickhouse_connect
from clickhouse_connect.driver.asyncclient import AsyncClient

from app.config import settings

logger = logging.getLogger(__name__)


async def create_client() -> AsyncClient:
    """Create a shared async ClickHouse client.

    Both ClickHouseWriter and ClickHouseReader should use the same instance
    to avoid redundant HTTP connections to the same server.
    connect_timeout and send_receive_timeout are set explicitly so long-running
    queries (forecast, correlation) don't hit the library default of 10s.
    """
    return await clickhouse_connect.get_async_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_database,
        connect_timeout=10,
        send_receive_timeout=300,
    )

_INSERT_COLUMNS = ["server_id", "metric_name", "value", "timestamp", "tags"]
_LOG_INSERT_COLUMNS = ["server_id", "log_file", "timestamp", "line"]
_RULE_INSERT_COLUMNS = ["rule_id", "server_id", "metric_name", "operator", "threshold",
                        "severity", "cooldown_minutes", "enabled", "created_at", "version",
                        "alert_mode", "ml_score_threshold"]
_EVENT_INSERT_COLUMNS = ["event_id", "rule_id", "server_id", "metric_name",
                         "value", "threshold", "severity", "state", "triggered_at"]
_FEATURE_INSERT_COLUMNS = [
    "server_id", "metric_name", "timestamp", "raw_value",
    "rolling_mean_5m", "rolling_std_5m", "rate_of_change",
    "hour_sin", "hour_cos", "day_of_week", "is_weekend",
]
_SCORE_INSERT_COLUMNS = ["server_id", "metric_name", "timestamp", "score", "model_version"]
_CHANNEL_INSERT_COLUMNS = ["channel_id", "rule_id", "server_id", "channel_type", "config",
                            "enabled", "created_at", "version"]
_SERVER_EVENT_INSERT_COLUMNS = ["event_id", "server_id", "event_type", "label", "metadata", "occurred_at"]
_CORRELATION_INSERT_COLUMNS = [
    "server_id", "event_type", "metric_name", "sample_count",
    "avg_delta", "avg_delta_pct", "p_value",
    "window_before_m", "window_after_m", "computed_at", "version",
]


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
    alert_mode: str = "static"        # static | ml | both
    ml_score_threshold: float = 0.7   # used when alert_mode in ('ml', 'both')


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
class AlertChannel:
    channel_id: UUID
    rule_id: UUID
    server_id: str
    channel_type: str   # 'webhook' | 'email' | 'slack'
    config: str         # JSON
    enabled: bool
    created_at: datetime


@dataclass
class ServerEvent:
    event_id: UUID
    server_id: str
    event_type: str
    label: str
    metadata: str       # JSON
    occurred_at: datetime


@dataclass
class CorrelationResult:
    server_id: str
    event_type: str
    metric_name: str
    sample_count: int
    avg_delta: float
    avg_delta_pct: float
    p_value: float
    window_before_m: int
    window_after_m: int
    computed_at: datetime


@dataclass
class SshStats:
    attempts_1h: int
    attempts_24h: int
    unique_ips_24h: int
    top_target: str | None


# ── Writer ────────────────────────────────────────────────────────────────────

class ClickHouseWriter:
    """Async batch writer. Receives a shared AsyncClient — does not own its lifecycle."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

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
            rule.alert_mode, rule.ml_score_threshold,
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

    async def insert_alert_channel(self, channel: AlertChannel) -> None:
        import time as _time
        data = [[
            channel.channel_id, channel.rule_id, channel.server_id,
            channel.channel_type, channel.config,
            int(channel.enabled), channel.created_at,
            int(_time.time() * 1000),
        ]]
        await self._client.insert("alert_channels", data=data, column_names=_CHANNEL_INSERT_COLUMNS)

    async def delete_alert_channel(self, channel_id: UUID) -> None:
        import time as _time
        # ReplacingMergeTree delete: re-insert with enabled=0 and higher version
        result = await self._client.query(
            "SELECT rule_id, server_id, channel_type, config, created_at"
            " FROM alert_channels FINAL"
            " WHERE channel_id = {cid:UUID} AND enabled = 1"
            " LIMIT 1",
            parameters={"cid": channel_id},
        )
        if not result.result_rows:
            return
        r = result.result_rows[0]
        data = [[channel_id, r[0], r[1], r[2], r[3], 0, r[4], int(_time.time() * 1000)]]
        await self._client.insert("alert_channels", data=data, column_names=_CHANNEL_INSERT_COLUMNS)

    async def insert_server_event(self, event: ServerEvent) -> None:
        data = [[
            event.event_id, event.server_id, event.event_type,
            event.label, event.metadata, event.occurred_at,
        ]]
        await self._client.insert("server_events", data=data, column_names=_SERVER_EVENT_INSERT_COLUMNS)

    async def insert_correlation_result(self, result: CorrelationResult) -> None:
        import time as _time
        data = [[
            result.server_id, result.event_type, result.metric_name,
            result.sample_count, result.avg_delta, result.avg_delta_pct,
            result.p_value, result.window_before_m, result.window_after_m,
            result.computed_at, int(_time.time() * 1000),
        ]]
        await self._client.insert("correlation_results", data=data, column_names=_CORRELATION_INSERT_COLUMNS)

    async def close(self) -> None:
        pass  # client lifecycle managed by the caller (main.py lifespan)


# ── Peak window helper ─────────────────────────────────────────────────────────

def _peak_window(fire_hours: list[int]) -> str:
    """Given a list of firing hours, return the most common 2h window or '—'."""
    if not fire_hours:
        return "—"
    counts: dict[int, int] = {}
    for h in fire_hours:
        counts[h] = counts.get(h, 0) + 1
    peak = max(counts, key=lambda h: counts[h])
    return f"{peak:02d}–{(peak + 1) % 24:02d}h"


# ── Reader ────────────────────────────────────────────────────────────────────

class ClickHouseReader:
    """Async reader for dashboard and API metric queries.

    Queries use the sort key (server_id, metric_name, timestamp) so ClickHouse
    can resolve them with a narrow granule scan — no full table scans.
    Receives a shared AsyncClient — does not own its lifecycle.
    """

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

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
                # coalesce handles both log patterns:
                #   'Failed password for [invalid user] <user> from' → first extract
                #   'Invalid user <user> from'                        → second extract
                "SELECT coalesce("
                "    nullIf(extract(line, 'for (?:invalid user )?(\\\\S+) from'), ''),"
                "    nullIf(extract(line, 'Invalid user (\\\\S+) from'), '')"
                ") AS u, count() AS cnt"
                " FROM logs"
                " WHERE server_id = {s:String} AND log_file = 'auth.log'"
                "   AND timestamp >= now() - INTERVAL 24 HOUR"
                "   AND match(line, 'Failed password|Invalid user')"
                " GROUP BY u HAVING u != '' ORDER BY cnt DESC LIMIT 1",
                parameters={"s": server_id},
            ),
        )
        return SshStats(
            attempts_1h=q_1h.result_rows[0][0] if q_1h.result_rows else 0,
            attempts_24h=q_24h.result_rows[0][0] if q_24h.result_rows else 0,
            unique_ips_24h=q_ips.result_rows[0][0] if q_ips.result_rows else 0,
            top_target=q_top.result_rows[0][0] or None if q_top.result_rows else None,
        )

    async def get_alert_rules(self, server_id: str) -> list[AlertRule]:
        result = await self._client.query(
            "SELECT rule_id, server_id, metric_name, operator, threshold,"
            "       severity, cooldown_minutes, enabled, created_at,"
            "       alert_mode, ml_score_threshold"
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
                alert_mode=r[9] or "static",
                ml_score_threshold=float(r[10]) if r[10] is not None else 0.7,
            )
            for r in result.result_rows
        ]

    async def get_latest_anomaly_score(self, server_id: str, metric_name: str) -> float | None:
        """Return the most recent anomaly score for a server/metric pair, or None."""
        result = await self._client.query(
            "SELECT score FROM anomaly_scores FINAL"
            " WHERE server_id = {server_id:String}"
            "   AND metric_name = {metric_name:String}"
            "   AND timestamp >= now() - INTERVAL 5 MINUTE"
            " ORDER BY timestamp DESC LIMIT 1",
            parameters={"server_id": server_id, "metric_name": metric_name},
        )
        if not result.result_rows:
            return None
        return float(result.result_rows[0][0])

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

    # ── V2 health snapshot helpers ────────────────────────────────────────────

    async def get_metric_baseline_7d(self, server_id: str, metric_name: str) -> float | None:
        result = await self._client.query(
            "SELECT round(avg(value), 1) FROM metrics"
            " WHERE server_id = {server_id:String}"
            "   AND metric_name = {metric_name:String}"
            "   AND timestamp >= now() - INTERVAL 7 DAY",
            parameters={"server_id": server_id, "metric_name": metric_name},
        )
        if not result.result_rows or result.result_rows[0][0] is None:
            return None
        return float(result.result_rows[0][0])

    async def get_metric_sparkline(
        self, server_id: str, metric_name: str, points: int = 30
    ) -> list[float]:
        """Return ~points evenly-sampled avg values over the last 60 minutes."""
        bucket = max(1, 60 // points)
        result = await self._client.query(
            f"SELECT round(avg(value), 1)"
            " FROM metrics"
            " WHERE server_id = {server_id:String}"
            "   AND metric_name = {metric_name:String}"
            "   AND timestamp >= now() - INTERVAL 60 MINUTE"
            f" GROUP BY toStartOfInterval(timestamp, INTERVAL {bucket} MINUTE)"
            f" ORDER BY toStartOfInterval(timestamp, INTERVAL {bucket} MINUTE)",
            parameters={"server_id": server_id, "metric_name": metric_name},
        )
        return [round(float(r[0]), 1) for r in result.result_rows]

    async def get_anomaly_count_6h(self, server_id: str) -> int:
        result = await self._client.query(
            "SELECT count() FROM anomaly_scores FINAL"
            " WHERE server_id = {server_id:String}"
            "   AND timestamp >= now() - INTERVAL 6 HOUR"
            "   AND score >= 0.5",
            parameters={"server_id": server_id},
        )
        return int(result.result_rows[0][0]) if result.result_rows else 0

    async def get_attack_by_hour(self, server_id: str) -> list[dict]:
        result = await self._client.query(
            "SELECT toHour(timestamp) AS h, count() AS cnt"
            " FROM logs"
            " WHERE server_id = {s:String}"
            "   AND log_file = 'auth.log'"
            "   AND timestamp >= toStartOfDay(now())"
            "   AND match(line, 'Failed password|Invalid user')"
            " GROUP BY h ORDER BY h",
            parameters={"s": server_id},
        )
        counts = {r[0]: r[1] for r in result.result_rows}
        return [{"hour": h, "count": counts.get(h, 0)} for h in range(24)]

    async def get_ssh_baseline_7d(self, server_id: str) -> float:
        result = await self._client.query(
            "SELECT avg(daily_count) FROM ("
            "  SELECT toStartOfDay(timestamp) AS day, count() AS daily_count"
            "  FROM logs"
            "  WHERE server_id = {s:String}"
            "    AND log_file = 'auth.log'"
            "    AND timestamp >= now() - INTERVAL 7 DAY"
            "    AND match(line, 'Failed password|Invalid user')"
            "  GROUP BY day"
            ")",
            parameters={"s": server_id},
        )
        if not result.result_rows or result.result_rows[0][0] is None:
            return 0.0
        return float(result.result_rows[0][0])

    async def get_attackers_grouped(self, server_id: str) -> list[dict]:
        result = await self._client.query(
            "SELECT"
            "  extract(line, 'from (\\\\S+) port') AS ip,"
            "  count() AS attempts,"
            "  groupUniqArray(coalesce("
            "    nullIf(extract(line, 'for (?:invalid user )?(\\\\S+) from'), ''),"
            "    nullIf(extract(line, 'Invalid user (\\\\S+) from'), '')"
            "  )) AS users,"
            "  max(timestamp) AS last_seen"
            " FROM logs"
            " WHERE server_id = {s:String}"
            "   AND log_file = 'auth.log'"
            "   AND timestamp >= now() - INTERVAL 24 HOUR"
            "   AND match(line, 'Failed password|Invalid user')"
            " GROUP BY ip HAVING ip != ''"
            " ORDER BY attempts DESC LIMIT 20",
            parameters={"s": server_id},
        )
        now = datetime.now(timezone.utc)
        rows = []
        for r in result.result_rows:
            last_seen_dt = r[3]
            if hasattr(last_seen_dt, "tzinfo") and last_seen_dt.tzinfo is None:
                last_seen_dt = last_seen_dt.replace(tzinfo=timezone.utc)
            elapsed_s = (now - last_seen_dt).total_seconds()
            rows.append({
                "ip": r[0],
                "attempts": r[1],
                "users": [u for u in r[2] if u],
                "last_seen": last_seen_dt.isoformat().replace("+00:00", "Z"),
                "blocked": elapsed_s > 1800,
            })
        return rows

    async def get_alert_rule_patterns(self, server_id: str) -> dict[str, dict]:
        result = await self._client.query(
            "SELECT rule_id, count() AS fires7d,"
            "       max(triggered_at) AS last_fire,"
            "       groupArray(toHour(triggered_at)) AS fire_hours"
            " FROM alert_events"
            " WHERE server_id = {s:String}"
            "   AND triggered_at >= now() - INTERVAL 7 DAY"
            "   AND state = 'FIRING'"
            " GROUP BY rule_id",
            parameters={"s": server_id},
        )
        patterns: dict[str, dict] = {}
        for r in result.result_rows:
            rule_id = str(r[0])
            fires7d = int(r[1])
            last_fire_dt = r[2]
            fire_hours: list[int] = r[3]
            if hasattr(last_fire_dt, "tzinfo") and last_fire_dt.tzinfo is None:
                last_fire_dt = last_fire_dt.replace(tzinfo=timezone.utc)
            patterns[rule_id] = {
                "fires7d": fires7d,
                "last_fire": last_fire_dt.isoformat().replace("+00:00", "Z") if last_fire_dt else None,
                "peak_window": _peak_window(fire_hours),
            }
        return patterns

    async def get_ufw_summary(self, server_id: str) -> dict:
        """Count UFW BLOCK events in the last 24h and check if ufw.log is present."""
        result = await self._client.query(
            "SELECT count() FROM logs"
            " WHERE server_id = {s:String}"
            "   AND log_file = 'ufw.log'"
            "   AND position(line, '[UFW BLOCK]') > 0"
            "   AND timestamp >= now() - INTERVAL 24 HOUR",
            parameters={"s": server_id},
        )
        blocks_24h = int(result.result_rows[0][0]) if result.result_rows else 0

        presence = await self._client.query(
            "SELECT count() FROM logs"
            " WHERE server_id = {s:String}"
            "   AND log_file = 'ufw.log'"
            "   AND timestamp >= now() - INTERVAL 7 DAY"
            " LIMIT 1",
            parameters={"s": server_id},
        )
        is_active = int(presence.result_rows[0][0]) > 0 if presence.result_rows else False

        return {"blocks_24h": blocks_24h, "is_active": is_active}

    async def get_ufw_top_ports(self, server_id: str, limit: int = 10) -> list[dict]:
        """Return the top blocked destination ports in the last 24h."""
        result = await self._client.query(
            "SELECT"
            "  extract(line, 'DPT=(\\\\d+)') AS port,"
            "  extract(line, 'PROTO=(\\\\w+)') AS proto,"
            "  count() AS blocks"
            " FROM logs"
            " WHERE server_id = {s:String}"
            "   AND log_file = 'ufw.log'"
            "   AND position(line, '[UFW BLOCK]') > 0"
            "   AND timestamp >= now() - INTERVAL 24 HOUR"
            "   AND port != ''"
            " GROUP BY port, proto"
            " ORDER BY blocks DESC"
            " LIMIT {limit:UInt32}",
            parameters={"s": server_id, "limit": limit},
        )
        return [
            {"port": int(r[0]), "proto": r[1], "blocks": int(r[2])}
            for r in result.result_rows
        ]

    # ── Capacity planning / forecasting ──────────────────────────────────────

    async def get_daily_aggregates(
        self, server_id: str, metric_name: str, days: int = 60
    ) -> list[dict]:
        """Return daily AVG of metric for the past N days, ordered ascending.

        Each row: {"date": "YYYY-MM-DD", "avg_value": float}
        Used as training data for the Prophet forecaster.
        """
        result = await self._client.query(
            "SELECT toDate(timestamp) AS day, avg(value) AS avg_val"
            " FROM metrics"
            " WHERE server_id = {server_id:String}"
            "   AND metric_name = {metric_name:String}"
            "   AND timestamp >= now() - INTERVAL {days:UInt32} DAY"
            " GROUP BY day"
            " ORDER BY day",
            parameters={"server_id": server_id, "metric_name": metric_name, "days": days},
        )
        return [
            {"date": str(r[0]), "avg_value": float(r[1])}
            for r in result.result_rows
        ]

    async def get_channels_for_rule(self, rule_id: UUID) -> list[AlertChannel]:
        result = await self._client.query(
            "SELECT channel_id, rule_id, server_id, channel_type, config, enabled, created_at"
            " FROM alert_channels FINAL"
            " WHERE rule_id = {rule_id:UUID} AND enabled = 1"
            " ORDER BY created_at",
            parameters={"rule_id": rule_id},
        )
        return [
            AlertChannel(
                channel_id=r[0], rule_id=r[1], server_id=r[2],
                channel_type=r[3], config=r[4], enabled=bool(r[5]), created_at=r[6],
            )
            for r in result.result_rows
        ]

    async def get_channels_for_server(self, server_id: str) -> list[AlertChannel]:
        result = await self._client.query(
            "SELECT channel_id, rule_id, server_id, channel_type, config, enabled, created_at"
            " FROM alert_channels FINAL"
            " WHERE server_id = {server_id:String} AND enabled = 1"
            " ORDER BY rule_id, created_at",
            parameters={"server_id": server_id},
        )
        return [
            AlertChannel(
                channel_id=r[0], rule_id=r[1], server_id=r[2],
                channel_type=r[3], config=r[4], enabled=bool(r[5]), created_at=r[6],
            )
            for r in result.result_rows
        ]

    async def get_server_events(
        self,
        server_id: str,
        limit: int = 100,
        event_type: str | None = None,
    ) -> list[ServerEvent]:
        params: dict = {"server_id": server_id, "limit": limit}
        type_filter = ""
        if event_type:
            type_filter = " AND event_type = {event_type:String}"
            params["event_type"] = event_type
        result = await self._client.query(
            "SELECT event_id, server_id, event_type, label, metadata, occurred_at"
            " FROM server_events"
            " WHERE server_id = {server_id:String}"
            + type_filter +
            " ORDER BY occurred_at DESC"
            " LIMIT {limit:UInt32}",
            parameters=params,
        )
        return [
            ServerEvent(
                event_id=r[0], server_id=r[1], event_type=r[2],
                label=r[3], metadata=r[4], occurred_at=r[5],
            )
            for r in result.result_rows
        ]

    async def get_correlation_results(self, server_id: str) -> list[CorrelationResult]:
        result = await self._client.query(
            "SELECT server_id, event_type, metric_name, sample_count,"
            "       avg_delta, avg_delta_pct, p_value,"
            "       window_before_m, window_after_m, computed_at"
            " FROM correlation_results FINAL"
            " WHERE server_id = {server_id:String}"
            " ORDER BY event_type, metric_name",
            parameters={"server_id": server_id},
        )
        return [
            CorrelationResult(
                server_id=r[0], event_type=r[1], metric_name=r[2],
                sample_count=r[3], avg_delta=r[4], avg_delta_pct=r[5],
                p_value=r[6], window_before_m=r[7], window_after_m=r[8],
                computed_at=r[9],
            )
            for r in result.result_rows
        ]

    async def get_metric_window(
        self,
        server_id: str,
        metric_name: str,
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, float]]:
        result = await self._client.query(
            "SELECT timestamp, value FROM metrics"
            " WHERE server_id = {server_id:String}"
            "   AND metric_name = {metric_name:String}"
            "   AND timestamp BETWEEN {start:DateTime} AND {end:DateTime}"
            " ORDER BY timestamp",
            parameters={"server_id": server_id, "metric_name": metric_name,
                        "start": start, "end": end},
        )
        return [(r[0], float(r[1])) for r in result.result_rows]

    async def close(self) -> None:
        pass  # client lifecycle managed by the caller (main.py lifespan)