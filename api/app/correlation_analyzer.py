from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

import numpy as np
from scipy import stats

from app.clickhouse import ClickHouseReader, ClickHouseWriter, CorrelationResult, ServerEvent
from app.config import settings

logger = logging.getLogger(__name__)

_RUN_INTERVAL_SECONDS = 86400  # nightly
_TRACKED_METRICS = [
    "cpu_usage_percent",
    "memory_usage_percent",
    "disk_usage_percent",
    "load_1m",
]
_MIN_SAMPLES = 3  # minimum events needed to produce a meaningful result


async def run_correlation_analyzer(reader: ClickHouseReader, writer: ClickHouseWriter) -> None:
    logger.info("correlation_analyzer: started (interval=%ds)", _RUN_INTERVAL_SECONDS)
    try:
        while True:
            await asyncio.sleep(_RUN_INTERVAL_SECONDS)
            try:
                await _run_analysis(reader, writer)
            except Exception as exc:
                logger.error("correlation_analyzer: analysis run failed: %s", exc)
    except asyncio.CancelledError:
        logger.info("correlation_analyzer: shutting down")


async def run_correlation_analyzer_once(reader: ClickHouseReader, writer: ClickHouseWriter) -> None:
    """Single on-demand run — used by the analysis endpoint."""
    await _run_analysis(reader, writer)


async def _run_analysis(reader: ClickHouseReader, writer: ClickHouseWriter) -> None:
    server_ids = await reader.get_known_server_ids()
    for server_id in server_ids:
        events = await reader.get_server_events(server_id, limit=500)
        if not events:
            continue
        event_types = {e.event_type for e in events}
        for event_type in event_types:
            typed_events = [e for e in events if e.event_type == event_type]
            if len(typed_events) < _MIN_SAMPLES:
                continue
            for metric_name in _TRACKED_METRICS:
                result = await _analyze(server_id, metric_name, typed_events, reader)
                if result is not None:
                    await writer.insert_correlation_result(result)
                    logger.info(
                        "correlation: %s / %s / %s — delta=%.2f%% p=%.3f n=%d",
                        server_id, event_type, metric_name,
                        result.avg_delta_pct, result.p_value, result.sample_count,
                    )


async def _analyze(
    server_id: str,
    metric_name: str,
    events: list[ServerEvent],
    reader: ClickHouseReader,
) -> CorrelationResult | None:
    before_m = settings.correlation_window_before_min
    after_m = settings.correlation_window_after_min

    deltas: list[float] = []
    baselines: list[float] = []

    for event in events:
        ts = event.occurred_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        pre_start = ts - timedelta(minutes=before_m)
        pre_end = ts
        post_start = ts
        post_end = ts + timedelta(minutes=after_m)

        pre_series = await reader.get_metric_window(server_id, metric_name, pre_start, pre_end)
        post_series = await reader.get_metric_window(server_id, metric_name, post_start, post_end)

        if not pre_series or not post_series:
            continue

        pre_avg = float(np.mean([v for _, v in pre_series]))
        post_avg = float(np.mean([v for _, v in post_series]))

        deltas.append(post_avg - pre_avg)
        baselines.append(pre_avg)

    if len(deltas) < _MIN_SAMPLES:
        return None

    arr = np.array(deltas)
    avg_delta = float(np.mean(arr))
    avg_baseline = float(np.mean(baselines))
    avg_delta_pct = (avg_delta / avg_baseline * 100) if avg_baseline != 0 else 0.0

    # One-sample t-test: is the mean delta significantly different from 0?
    _, p_value = stats.ttest_1samp(arr, 0)

    return CorrelationResult(
        server_id=server_id,
        event_type=events[0].event_type,
        metric_name=metric_name,
        sample_count=len(deltas),
        avg_delta=avg_delta,
        avg_delta_pct=avg_delta_pct,
        p_value=float(p_value),
        window_before_m=before_m,
        window_after_m=after_m,
        computed_at=datetime.now(timezone.utc),
    )
