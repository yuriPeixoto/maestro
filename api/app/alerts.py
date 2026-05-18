from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, HttpUrl

from app.clickhouse import AlertRule, ClickHouseReader
from app.logs import _utc_iso

router = APIRouter(prefix="/alerts", tags=["alerts"])


# ── Request / Response models ─────────────────────────────────────────────────

class AlertRuleIn(BaseModel):
    metric_name: str
    operator: str = Field(pattern=r"^(>|<|>=|<=|==)$")
    threshold: float
    severity: str = Field(pattern=r"^(warning|critical)$")
    cooldown_minutes: int = Field(default=5, ge=1, le=1440)


class AlertRuleOut(BaseModel):
    rule_id: str
    server_id: str
    metric_name: str
    operator: str
    threshold: float
    severity: str
    cooldown_minutes: int
    created_at: str


class AlertEventOut(BaseModel):
    event_id: str
    rule_id: str
    metric_name: str
    value: float
    threshold: float
    severity: str
    state: str
    triggered_at: str


class AlertsResponse(BaseModel):
    server_id: str
    events: list[AlertEventOut]


class RulesResponse(BaseModel):
    server_id: str
    rules: list[AlertRuleOut]


class WebhookConfigIn(BaseModel):
    url: HttpUrl


class WebhookConfigOut(BaseModel):
    server_id: str
    url: str | None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/{server_id}/events", response_model=AlertsResponse)
async def get_alert_events(server_id: str, request: Request, limit: int = 100) -> AlertsResponse:
    reader: ClickHouseReader = request.app.state.ch_reader
    events = await reader.get_alert_events(server_id, limit=limit)
    return AlertsResponse(
        server_id=server_id,
        events=[
            AlertEventOut(
                event_id=str(e.event_id),
                rule_id=str(e.rule_id),
                metric_name=e.metric_name,
                value=e.value,
                threshold=e.threshold,
                severity=e.severity,
                state=e.state,
                triggered_at=_utc_iso(e.triggered_at),
            )
            for e in events
        ],
    )


@router.get("/{server_id}/rules", response_model=RulesResponse)
async def get_alert_rules(server_id: str, request: Request) -> RulesResponse:
    reader: ClickHouseReader = request.app.state.ch_reader
    rules = await reader.get_alert_rules(server_id)
    return RulesResponse(
        server_id=server_id,
        rules=[_rule_out(r) for r in rules],
    )


@router.post("/{server_id}/rules", response_model=AlertRuleOut, status_code=201)
async def create_alert_rule(server_id: str, body: AlertRuleIn, request: Request) -> AlertRuleOut:
    from app.clickhouse import ClickHouseWriter
    writer: ClickHouseWriter = request.app.state.ch_writer
    now = datetime.now(timezone.utc)
    rule = AlertRule(
        rule_id=uuid4(),
        server_id=server_id,
        metric_name=body.metric_name,
        operator=body.operator,
        threshold=body.threshold,
        severity=body.severity,
        cooldown_minutes=body.cooldown_minutes,
        enabled=True,
        created_at=now,
    )
    await writer.insert_alert_rule(rule)
    return _rule_out(rule)


@router.delete("/{server_id}/rules/{rule_id}", status_code=204)
async def delete_alert_rule(server_id: str, rule_id: str, request: Request) -> None:
    from app.clickhouse import AlertRule, ClickHouseWriter
    writer: ClickHouseWriter = request.app.state.ch_writer
    reader: ClickHouseReader = request.app.state.ch_reader

    rules = await reader.get_alert_rules(server_id)
    target = next((r for r in rules if str(r.rule_id) == rule_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Rule not found")

    # Soft-delete via ReplacingMergeTree: insert disabled version with higher version number.
    disabled = AlertRule(
        rule_id=target.rule_id, server_id=target.server_id,
        metric_name=target.metric_name, operator=target.operator,
        threshold=target.threshold, severity=target.severity,
        cooldown_minutes=target.cooldown_minutes, enabled=False,
        created_at=target.created_at,
    )
    await writer.insert_alert_rule(disabled)


_WEBHOOK_KEY = "maestro:webhook:{server_id}"


@router.get("/{server_id}/webhook", response_model=WebhookConfigOut)
async def get_webhook(server_id: str, request: Request) -> WebhookConfigOut:
    import redis.asyncio as aioredis
    from app.config import settings
    redis: aioredis.Redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        url = await redis.get(_WEBHOOK_KEY.format(server_id=server_id))
    finally:
        await redis.aclose()
    return WebhookConfigOut(server_id=server_id, url=url)


@router.put("/{server_id}/webhook", response_model=WebhookConfigOut)
async def save_webhook(server_id: str, body: WebhookConfigIn, request: Request) -> WebhookConfigOut:
    import redis.asyncio as aioredis
    from app.config import settings
    redis: aioredis.Redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    url = str(body.url)
    try:
        await redis.set(_WEBHOOK_KEY.format(server_id=server_id), url)
    finally:
        await redis.aclose()
    return WebhookConfigOut(server_id=server_id, url=url)


@router.delete("/{server_id}/webhook", status_code=204)
async def delete_webhook(server_id: str, request: Request) -> None:
    import redis.asyncio as aioredis
    from app.config import settings
    redis: aioredis.Redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis.delete(_WEBHOOK_KEY.format(server_id=server_id))
    finally:
        await redis.aclose()


def _rule_out(r: AlertRule) -> AlertRuleOut:
    return AlertRuleOut(
        rule_id=str(r.rule_id),
        server_id=r.server_id,
        metric_name=r.metric_name,
        operator=r.operator,
        threshold=r.threshold,
        severity=r.severity,
        cooldown_minutes=r.cooldown_minutes,
        created_at=_utc_iso(r.created_at),
    )
