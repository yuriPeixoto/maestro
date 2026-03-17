import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.clickhouse import ClickHouseReader
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["metrics"])


# ── Response models ───────────────────────────────────────────────────────────

class DataPoint(BaseModel):
    timestamp: str
    value: float


class MetricSeriesResponse(BaseModel):
    server_id: str
    metric: str
    minutes: int
    data: list[DataPoint]


class MetricNamesResponse(BaseModel):
    server_id: str
    metrics: list[str]


# ── Dependency ────────────────────────────────────────────────────────────────

def get_reader(request: Request) -> ClickHouseReader:
    return request.app.state.ch_reader


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/{server_id}", response_model=MetricNamesResponse)
async def list_metrics(
    server_id: str,
    reader: ClickHouseReader = Depends(get_reader),
):
    """Return the list of distinct metric names available for a server."""
    names = await reader.get_metric_names(server_id)
    if not names:
        raise HTTPException(
            status_code=404,
            detail=f"No metrics found for server '{server_id}'",
        )
    return MetricNamesResponse(server_id=server_id, metrics=names)


@router.get("/{server_id}/{metric_name}", response_model=MetricSeriesResponse)
async def get_metric_series(
    server_id: str,
    metric_name: str,
    minutes: int = Query(
        default=settings.metrics_query_default_minutes,
        ge=1,
        le=settings.metrics_query_max_minutes,
        description="Time window in minutes (1–1440). Defaults to 30.",
    ),
    reader: ClickHouseReader = Depends(get_reader),
):
    """Return time-series data for a specific server and metric.

    Query uses the ClickHouse sort key (server_id, metric_name, timestamp)
    directly — no full table scans.
    """
    points = await reader.get_metric_series(server_id, metric_name, minutes)
    return MetricSeriesResponse(
        server_id=server_id,
        metric=metric_name,
        minutes=minutes,
        data=[
            DataPoint(timestamp=p.timestamp.isoformat(), value=p.value)
            for p in points
        ],
    )