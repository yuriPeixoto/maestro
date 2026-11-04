"""Per-minute views of a server's metrics: the input of anomaly detection.

Raw samples arrive every 5–60 seconds, one row per device or interface. Detection
works on one value per metric per minute, which smooths sampling noise and lines
the metrics up so they can be compared at the same instant:

- rates (`*_per_sec`) are summed across devices and interfaces (total throughput);
- everything else is averaged.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

# The metrics anomaly detection looks at. Byte counters that repeat a percentage
# (memory_used_bytes, disk_used_bytes) and fixed sizes (disk_total_bytes) are left
# out: they add no information and would report the same event twice. Disk usage only
# grows, so it belongs to capacity planning, not to "unusual for this hour".
ANOMALY_METRICS: tuple[str, ...] = (
    "cpu_usage_percent",
    "memory_usage_percent",
    "disk_read_bytes_per_sec",
    "disk_write_bytes_per_sec",
    "network_bytes_in_per_sec",
    "network_bytes_out_per_sec",
    "process_count",
)

# Metrics whose trend capacity planning forecasts.
CAPACITY_METRICS: tuple[str, ...] = ("disk_usage_percent", "memory_usage_percent", "cpu_usage_percent")

_RATE_SUFFIX = "_per_sec"

_MINUTE_FRAME_SQL = """
SELECT minute, metric_name, if(endsWith(metric_name, {rate_suffix:String}), sum(v), avg(v)) AS value
FROM (
    SELECT toStartOfMinute(timestamp) AS minute, metric_name, tags, avg(value) AS v
    FROM metrics
    WHERE server_id = {server_id:String}
      AND metric_name IN {metrics:Array(String)}
      AND timestamp >= {start:DateTime} AND timestamp < {end:DateTime}
    GROUP BY minute, metric_name, tags
)
GROUP BY minute, metric_name
ORDER BY minute
"""


def minute_frame_query(
    server_id: str, start: datetime, end: datetime, metrics: tuple[str, ...] = ANOMALY_METRICS,
) -> tuple[str, dict]:
    """SQL and parameters for one value per metric per minute in [start, end)."""
    return _MINUTE_FRAME_SQL, {
        "server_id": server_id,
        "metrics": list(metrics),
        "start": start,
        "end": end,
        "rate_suffix": _RATE_SUFFIX,
    }


def to_minute_frame(
    rows: list[tuple], start: datetime, end: datetime, metrics: tuple[str, ...] = ANOMALY_METRICS,
) -> pd.DataFrame:
    """Pivot (minute, metric, value) rows into one row per minute and one column per metric.

    Every minute of [start, end) is present; minutes without data (agent down) stay NaN.
    """
    index = pd.date_range(_utc(start), _utc(end), freq="1min", inclusive="left", name="minute")
    if not rows:
        return pd.DataFrame(index=index, columns=list(metrics), dtype=float)
    long = pd.DataFrame(rows, columns=["minute", "metric_name", "value"])
    long["minute"] = pd.to_datetime(long["minute"], utc=True)
    wide = long.pivot_table(index="minute", columns="metric_name", values="value", aggfunc="mean")
    wide = wide.reindex(index=index, columns=list(metrics))
    wide.columns.name = None
    return wide.astype(float)


def _utc(moment: datetime) -> pd.Timestamp:
    stamp = pd.Timestamp(moment)
    return stamp.tz_convert("UTC") if stamp.tzinfo else stamp.tz_localize("UTC")


async def fetch_minute_frame(
    client, server_id: str, start: datetime, end: datetime,
    metrics: tuple[str, ...] = ANOMALY_METRICS, settings: dict | None = None,
) -> pd.DataFrame:
    sql, parameters = minute_frame_query(server_id, start, end, metrics)
    result = await client.query(sql, parameters=parameters, settings=settings)
    return to_minute_frame(result.result_rows, start, end, metrics)
