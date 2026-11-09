from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field

from app import alert_store
from app.alert_store import AlertRule, DuplicateRule
from app.clickhouse import ClickHouseReader
from app.logs import _utc_iso
from app.rule_values import current_rule_value
from app.auth import require
from app.permissions import Permission

router = APIRouter(prefix="/alerts", tags=["alerts"])

# Writes need a role that grants it (app.permissions); reads only a login.
_MANAGE_ALERTS = [Depends(require(Permission.MANAGE_ALERTS))]


# ── Request / Response models ─────────────────────────────────────────────────

class AlertRuleIn(BaseModel):
    metric_name: str
    operator: str = Field(pattern=r"^(>|<|>=|<=|==)$")
    threshold: float
    severity: str = Field(pattern=r"^(warning|critical)$")
    cooldown_minutes: int = Field(default=5, ge=1, le=1440)
    alert_mode: str = Field(default="static", pattern=r"^(static|ml|both)$")
    ml_score_threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class AlertRuleOut(BaseModel):
    rule_id: str
    scope: str               # where the rule is set: global | group | server
    server_id: str | None
    group_id: int | None
    metric_name: str
    operator: str
    threshold: float
    severity: str
    cooldown_minutes: int
    created_at: str
    alert_mode: str
    ml_score_threshold: float
    enabled: bool


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
async def get_alert_rules(server_id: str) -> RulesResponse:
    """The rules judged on this server, wherever each one is set (scope says where)."""
    rules = await alert_store.effective_rules(server_id)
    return RulesResponse(server_id=server_id, rules=[rule_out(r) for r in rules])


@router.post("/{server_id}/rules", response_model=AlertRuleOut, status_code=201, dependencies=_MANAGE_ALERTS)
async def create_alert_rule(server_id: str, body: AlertRuleIn) -> AlertRuleOut:
    rule = AlertRule(
        rule_id=uuid4(),
        server_id=server_id,
        metric_name=body.metric_name,
        operator=body.operator,
        threshold=body.threshold,
        severity=body.severity,
        cooldown_minutes=body.cooldown_minutes,
        created_at=datetime.now(timezone.utc),
        alert_mode=body.alert_mode,
        ml_score_threshold=body.ml_score_threshold,
    )
    try:
        await alert_store.create_rule(rule)
    except DuplicateRule:
        raise HTTPException(
            status_code=409, detail="This server already has a rule for this metric and severity",
        ) from None
    return rule_out(rule)


@router.delete("/{server_id}/rules/{rule_id}", status_code=204, dependencies=_MANAGE_ALERTS)
async def delete_alert_rule(server_id: str, rule_id: UUID) -> None:
    if await alert_store.delete_rule(server_id, rule_id):
        return
    if await alert_store.rule_exists(server_id, rule_id):
        raise HTTPException(
            status_code=409, detail="This rule is set for a group or every server; change it there",
        )
    raise HTTPException(status_code=404, detail="Rule not found")


def rule_out(r: AlertRule) -> AlertRuleOut:
    return AlertRuleOut(
        rule_id=str(r.rule_id),
        scope=r.scope,
        server_id=r.server_id,
        group_id=r.group_id,
        metric_name=r.metric_name,
        operator=r.operator,
        threshold=r.threshold,
        severity=r.severity,
        cooldown_minutes=r.cooldown_minutes,
        created_at=_utc_iso(r.created_at),
        alert_mode=r.alert_mode,
        ml_score_threshold=r.ml_score_threshold,
        enabled=r.enabled,
    )


# ── Rule patterns (V2) ────────────────────────────────────────────────────────

class RulePattern(BaseModel):
    rule_id: str
    fires7d: int
    last_fire: str | None
    peak_window: str
    current_value: float | None
    state: str   # "dormant" | "quiet" | "active" | "firing"


class RulePatternsResponse(BaseModel):
    server_id: str
    patterns: list[RulePattern]


@router.get("/{server_id}/rule-patterns", response_model=RulePatternsResponse)
async def get_rule_patterns(server_id: str, request: Request) -> RulePatternsResponse:
    reader: ClickHouseReader = request.app.state.ch_reader

    rules, raw_patterns, open_alerts = await asyncio.gather(
        alert_store.effective_rules(server_id),
        reader.get_alert_rule_patterns(server_id),
        alert_store.firing_severities(server_id),
    )

    redis = request.app.state.vuln_redis
    current_values = await asyncio.gather(
        *[current_rule_value(reader, redis, server_id, r.metric_name) for r in rules]
    )

    patterns: list[RulePattern] = []
    for rule, cur_val in zip(rules, current_values):
        rid = str(rule.rule_id)
        p = raw_patterns.get(rid, {})
        fires7d = p.get("fires7d", 0)

        if rid in open_alerts:
            state = "firing"
        elif fires7d == 0:
            state = "dormant"
        elif p.get("last_fire") and _is_recent(p["last_fire"]):
            state = "active"
        else:
            state = "quiet"

        patterns.append(RulePattern(
            rule_id=rid,
            fires7d=fires7d,
            last_fire=p.get("last_fire"),
            peak_window=p.get("peak_window", "—"),
            current_value=cur_val,
            state=state,
        ))
    return RulePatternsResponse(server_id=server_id, patterns=patterns)


def _is_recent(iso: str) -> bool:
    """True if ISO timestamp is within the last 24 hours."""
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() < 86400
    except Exception:
        return False
