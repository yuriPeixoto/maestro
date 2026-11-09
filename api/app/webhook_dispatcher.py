from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.clickhouse import AlertEvent
from app.delivery import Notification, post_json


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _event_fields(event: AlertEvent) -> dict:
    return {
        "rule_id": str(event.rule_id),
        "event_id": str(event.event_id),
        "metric_name": event.metric_name,
        "value": event.value,
        "threshold": event.threshold,
        "severity": event.severity,
        "state": event.state,
        "triggered_at": _iso(event.triggered_at) if isinstance(event.triggered_at, datetime) else str(event.triggered_at),
    }


def build_payload(notification: Notification) -> dict:
    """The single alert's fields at the top, as before 0.3.0, and every line in `alerts`."""
    payload: dict = {
        "kind": notification.kind,
        "text": notification.text,
        "server_id": notification.server_id,
    }
    if notification.event is not None:
        payload.update(_event_fields(notification.event))
    if notification.lines:
        payload["alerts"] = [
            {"kind": line.kind, "text": line.text, **_event_fields(line.event)} for line in notification.lines
        ]
    return payload


async def send(config: dict, notification: Notification, client: httpx.AsyncClient) -> None:
    await post_json(client, config["url"], build_payload(notification), "webhook")
