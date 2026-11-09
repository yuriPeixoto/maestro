"""Alerts open now (firing or without data), acknowledging one, and deliveries waiting for a retry.

Acknowledging says "someone is on it": the alert stays open and stops repeating. The
channels that heard the alert hear who acknowledged it, unless a silence or maintenance
keeps the alert quiet. It is audited as an event; the state row itself is not audited,
because the evaluator changes it all the time.
"""
from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app import alert_outbox, alert_store, audit, notification_retries, server_store
from app.alert_outbox import Outgoing
from app.alert_store import AlreadyAcknowledged, NotOpen, OpenAlert
from app.auth import require
from app.clickhouse import AlertEvent
from app.delivery import KIND_ACKNOWLEDGED, Line
from app.logs import _utc_iso
from app.notification_text import acknowledged_text
from app.permissions import Permission
from app.quiet import quiet_now
from app.rule_values import current_rule_value

router = APIRouter(prefix="/alerts", tags=["alerts"])

_acknowledge = require(Permission.ACKNOWLEDGE_ALERTS)


class OpenAlertOut(BaseModel):
    rule_id: str
    server_id: str
    scope: str
    metric_name: str
    operator: str
    threshold: float
    severity: str
    cooldown_minutes: int            # the alert repeats this often until acknowledged
    value: float | None              # the value now; None without data
    state: str                       # FIRING | NO_DATA
    since: str | None
    acknowledged_at: str | None
    acknowledged_by: str | None
    quiet: str | None                # silence | maintenance: the channels are not told now


class RetryOut(BaseModel):
    retry_id: int
    channel_id: str
    attempts: int
    max_attempts: int
    next_attempt_at: str
    first_attempt_at: str
    last_error: str
    kinds: list[str]


def _iso(moment) -> str | None:
    return _utc_iso(moment) if moment is not None else None


async def _still_judged(alerts: list[OpenAlert]) -> tuple[list[OpenAlert], dict[str, int | None]]:
    """Drop states of rules no longer judged on their server (overridden, switched off)."""
    servers = sorted({a.server_id for a in alerts})
    items = await alert_store.rules_to_evaluate(servers)
    judged = {(item.rule.rule_id, item.server_id) for item in items}
    groups = {item.server_id: item.group_id for item in items}
    return [a for a in alerts if (a.rule.rule_id, a.server_id) in judged], groups


def _out(alert: OpenAlert, quiet: str | None, value: float | None = None) -> OpenAlertOut:
    rule, state = alert.rule, alert.state
    return OpenAlertOut(
        rule_id=str(rule.rule_id), server_id=alert.server_id, scope=rule.scope, metric_name=rule.metric_name,
        operator=rule.operator, threshold=rule.threshold, severity=rule.severity,
        cooldown_minutes=rule.cooldown_minutes, value=value, state=state.state,
        # Rows from before 0.3.0 have no changed_at; the last firing is the best guess.
        since=_iso(state.changed_at or state.last_fired_at), acknowledged_at=_iso(state.acknowledged_at),
        acknowledged_by=alert.acknowledged_by_name, quiet=quiet,
    )


@router.get("/open", response_model=list[OpenAlertOut])
async def list_open_alerts(request: Request, server_id: str | None = None) -> list[OpenAlertOut]:
    alerts, groups = await _still_judged(await alert_store.open_alerts(server_id))
    reader, redis = request.app.state.ch_reader, request.app.state.vuln_redis
    quiet, values = await asyncio.gather(
        quiet_now(),
        asyncio.gather(*[current_rule_value(reader, redis, a.server_id, a.rule.metric_name) for a in alerts]),
    )
    return [
        _out(a, quiet.reason(a.server_id, groups.get(a.server_id), a.rule.rule_id), value)
        for a, value in zip(alerts, values)
    ]


@router.post("/{server_id}/rules/{rule_id}/acknowledge", response_model=OpenAlertOut)
async def acknowledge_alert(
    server_id: str, rule_id: UUID, request: Request, user: dict = Depends(_acknowledge),
) -> OpenAlertOut:
    try:
        state = await alert_store.acknowledge(rule_id, server_id, user["id"])
    except NotOpen:
        raise HTTPException(status_code=404, detail="No open alert of this rule on this server") from None
    except AlreadyAcknowledged:
        raise HTTPException(status_code=409, detail="Someone acknowledged this alert already") from None
    rule = await alert_store.get_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    await audit.record(
        "alert_state.acknowledge", target_table="alert_state", target_id=f"{rule_id}:{server_id}",
        details={"rule_id": str(rule_id), "server_id": server_id, "state": state.state},
    )
    alert = OpenAlert(rule, server_id, state, user["username"])
    group_id = await alert_store.group_of(server_id)
    quiet = (await quiet_now()).reason(server_id, group_id, rule_id)
    if quiet is None and state.last_event_id is not None:
        await _tell_channels(alert, group_id, request)
    return _out(alert, quiet)


async def _tell_channels(alert: OpenAlert, group_id: int | None, request: Request) -> None:
    rule, state = alert.rule, alert.state
    event = AlertEvent(
        event_id=state.last_event_id, rule_id=rule.rule_id, server_id=alert.server_id,
        metric_name=rule.metric_name, value=0.0, threshold=rule.threshold, severity=rule.severity,
        state=state.state, triggered_at=state.changed_at or state.acknowledged_at,
    )
    label = await server_store.label_of(alert.server_id)
    text = acknowledged_text(event, alert.acknowledged_by_name or "", label)
    outgoing = [Outgoing(Line(KIND_ACKNOWLEDGED, text, event), group_id)]
    alert_outbox.send_soon(outgoing, request.app.state.ch_writer, {alert.server_id: label} if label else None)


@router.get("/{server_id}/retries", response_model=list[RetryOut])
async def list_retries(server_id: str) -> list[RetryOut]:
    return [
        RetryOut(
            retry_id=r["retry_id"], channel_id=str(r["channel_id"]), attempts=r["attempts"],
            max_attempts=r["max_attempts"], next_attempt_at=_utc_iso(r["next_attempt_at"]),
            first_attempt_at=_utc_iso(r["first_attempt_at"]), last_error=r["last_error"], kinds=r["kinds"],
        )
        for r in await notification_retries.pending(server_id)
    ]
