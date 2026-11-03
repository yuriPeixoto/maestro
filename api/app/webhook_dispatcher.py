from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.delivery import Notification, post_json


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_payload(notification: Notification) -> dict:
    payload: dict = {
        "kind": notification.kind,
        "text": notification.text,
        "server_id": notification.server_id,
    }
    event = notification.event
    if event is not None:
        payload.update({
            "rule_id": str(event.rule_id),
            "metric_name": event.metric_name,
            "value": event.value,
            "threshold": event.threshold,
            "severity": event.severity,
            "state": event.state,
            "triggered_at": _iso(event.triggered_at) if isinstance(event.triggered_at, datetime) else str(event.triggered_at),
        })
    return payload


async def send(config: dict, notification: Notification, client: httpx.AsyncClient) -> None:
    await post_json(client, config["url"], build_payload(notification), "webhook")
