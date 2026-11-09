"""Rules and channels at any place: every server (`global`), a group or one server (ADR-013).

The per-server routes in app.alerts and app.alert_channels stay as they were for the
screen; these take the place in the request. For each metric and severity a server is
judged by the most specific rule (GET /alerts/{server_id}/resolved-rules shows which
one wins there and what it overrides); channels add up.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app import alert_store
from app.alert_channels import ChannelIn, ChannelOut, DeliveryOut, channel_out, checked_config, send_test
from app.alert_store import AlertChannel, AlertRule, DuplicateRule, UnknownGroup
from app.alerts import AlertRuleIn, AlertRuleOut, rule_out
from app.auth import require
from app.permissions import Permission
from app.rule_scope import Place

router = APIRouter(prefix="/alerts", tags=["alerts"])

_MANAGE_ALERTS = [Depends(require(Permission.MANAGE_ALERTS))]

ScopeName = Literal["global", "group", "server"]


class PlaceIn(BaseModel):
    scope: ScopeName
    server_id: str | None = Field(default=None, min_length=1, max_length=255)
    group_id: int | None = None

    def place(self) -> Place:
        return place_of(self.scope, self.server_id, self.group_id)


def place_of(scope: str, server_id: str | None, group_id: int | None) -> Place:
    try:
        return Place(scope, server_id, group_id)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="scope 'global' takes neither server_id nor group_id, 'group' takes group_id, 'server' takes server_id",
        ) from None


class ScopedRuleIn(AlertRuleIn, PlaceIn):
    enabled: bool = True


class RuleChangesIn(BaseModel):
    operator: str | None = Field(default=None, pattern=r"^(>|<|>=|<=|==)$")
    threshold: float | None = None
    cooldown_minutes: int | None = Field(default=None, ge=1, le=1440)
    alert_mode: str | None = Field(default=None, pattern=r"^(static|ml|both)$")
    ml_score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    enabled: bool | None = None


class ScopedChannelIn(ChannelIn, PlaceIn):
    pass


class ResolvedRuleOut(BaseModel):
    rule: AlertRuleOut
    # Rules of broader places for the same metric and severity that this one overrides.
    overrides: list[AlertRuleOut]


# ── Rules ─────────────────────────────────────────────────────────────────────

@router.get("/rules", response_model=list[AlertRuleOut])
async def list_rules_at(
    scope: ScopeName = Query(...), server_id: str | None = None, group_id: int | None = None,
) -> list[AlertRuleOut]:
    return [rule_out(r) for r in await alert_store.rules_at(place_of(scope, server_id, group_id))]


@router.post("/rules", response_model=AlertRuleOut, status_code=201, dependencies=_MANAGE_ALERTS)
async def create_rule_at(body: ScopedRuleIn) -> AlertRuleOut:
    place = body.place()
    rule = AlertRule(
        rule_id=uuid4(), server_id=place.server_id, metric_name=body.metric_name, operator=body.operator,
        threshold=body.threshold, severity=body.severity, cooldown_minutes=body.cooldown_minutes,
        created_at=datetime.now(timezone.utc), alert_mode=body.alert_mode,
        ml_score_threshold=body.ml_score_threshold, scope=place.scope, group_id=place.group_id, enabled=body.enabled,
    )
    try:
        await alert_store.create_rule(rule)
    except DuplicateRule:
        raise HTTPException(status_code=409, detail="This place already has a rule for this metric and severity") from None
    except UnknownGroup:
        raise HTTPException(status_code=404, detail="Group not found") from None
    return rule_out(rule)


@router.patch("/rules/{rule_id}", response_model=AlertRuleOut, dependencies=_MANAGE_ALERTS)
async def update_rule(rule_id: UUID, body: RuleChangesIn) -> AlertRuleOut:
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to change")
    rule = await alert_store.update_rule(rule_id, changes)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule_out(rule)


@router.delete("/rules/{rule_id}", status_code=204, dependencies=_MANAGE_ALERTS)
async def delete_rule(rule_id: UUID) -> Response:
    if not await alert_store.delete_rule_by_id(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return Response(status_code=204)


@router.get("/{server_id}/resolved-rules", response_model=list[ResolvedRuleOut])
async def resolved_rules(server_id: str) -> list[ResolvedRuleOut]:
    """Per metric and severity, the rule that wins on this server (switched off or not)."""
    return [
        ResolvedRuleOut(rule=rule_out(item.rule), overrides=[rule_out(r) for r in item.overrides])
        for item in await alert_store.resolved_rules(server_id)
    ]


# ── Channels ──────────────────────────────────────────────────────────────────

@router.get("/channels", response_model=list[ChannelOut])
async def list_channels_at(
    scope: ScopeName = Query(...), server_id: str | None = None, group_id: int | None = None,
) -> list[ChannelOut]:
    return [channel_out(ch) for ch in await alert_store.channels_at(place_of(scope, server_id, group_id))]


@router.post("/channels", response_model=ChannelOut, status_code=201, dependencies=_MANAGE_ALERTS)
async def create_channel_at(body: ScopedChannelIn) -> ChannelOut:
    place = body.place()
    config = checked_config(body)
    if body.rule_id is not None and await alert_store.get_rule(body.rule_id) is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    channel = AlertChannel(
        channel_id=uuid4(), rule_id=body.rule_id, server_id=place.server_id, channel_type=body.channel_type,
        config=config, created_at=datetime.now(timezone.utc), scope=place.scope, group_id=place.group_id,
    )
    try:
        await alert_store.create_channel(channel)
    except UnknownGroup:
        raise HTTPException(status_code=404, detail="Group not found") from None
    return channel_out(channel)


async def _channel(channel_id: UUID) -> AlertChannel:
    channel = await alert_store.get_channel_by_id(channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


@router.delete("/channels/{channel_id}", status_code=204, dependencies=_MANAGE_ALERTS)
async def delete_channel(channel_id: UUID) -> Response:
    if not await alert_store.delete_channel_by_id(channel_id):
        raise HTTPException(status_code=404, detail="Channel not found")
    return Response(status_code=204)


@router.post("/channels/{channel_id}/test", response_model=DeliveryOut, dependencies=_MANAGE_ALERTS)
async def test_channel(channel_id: UUID, request: Request) -> DeliveryOut:
    return await send_test(await _channel(channel_id), request)
