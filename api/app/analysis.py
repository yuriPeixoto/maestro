from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel

from app.clickhouse import ClickHouseReader, ClickHouseWriter
from app.logs import _utc_iso

router = APIRouter(prefix="/analysis", tags=["analysis"])


class CorrelationResultOut(BaseModel):
    event_type: str
    metric_name: str
    sample_count: int
    avg_delta: float
    avg_delta_pct: float
    p_value: float
    significant: bool       # p_value < 0.05
    window_before_m: int
    window_after_m: int
    computed_at: str
    summary: str            # human-readable sentence


def _build_summary(event_type: str, metric_name: str, avg_delta_pct: float, p_value: float, sample_count: int) -> str:
    direction = "increases" if avg_delta_pct > 0 else "decreases"
    significance = "statistically significant" if p_value < 0.05 else "not statistically significant"
    return (
        f"After {event_type} events, {metric_name} {direction} by "
        f"{abs(avg_delta_pct):.1f}% on average "
        f"({significance}, n={sample_count})."
    )


@router.get("/{server_id}/correlations", response_model=list[CorrelationResultOut])
async def get_correlations(server_id: str, request: Request) -> list[CorrelationResultOut]:
    reader: ClickHouseReader = request.app.state.ch_reader
    results = await reader.get_correlation_results(server_id)
    return [
        CorrelationResultOut(
            event_type=r.event_type,
            metric_name=r.metric_name,
            sample_count=r.sample_count,
            avg_delta=r.avg_delta,
            avg_delta_pct=r.avg_delta_pct,
            p_value=r.p_value,
            significant=r.p_value < 0.05,
            window_before_m=r.window_before_m,
            window_after_m=r.window_after_m,
            computed_at=_utc_iso(r.computed_at),
            summary=_build_summary(
                r.event_type, r.metric_name, r.avg_delta_pct, r.p_value, r.sample_count
            ),
        )
        for r in results
    ]


@router.post("/{server_id}/correlations/run", status_code=202)
async def trigger_analysis(server_id: str, request: Request, background_tasks: BackgroundTasks) -> dict:
    """Trigger an on-demand correlation analysis run for a single server."""
    from app.correlation_analyzer import run_correlation_analyzer_once
    reader: ClickHouseReader = request.app.state.ch_reader
    writer: ClickHouseWriter = request.app.state.ch_writer
    background_tasks.add_task(run_correlation_analyzer_once, reader, writer)
    return {"status": "accepted", "server_id": server_id}
