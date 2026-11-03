from __future__ import annotations

import httpx

from app.delivery import KIND_FIRING, Notification, post_json

_COLOR_FIRING = "#e53e3e"
_COLOR_CALM = "#38a169"


def build_payload(notification: Notification) -> dict:
    color = _COLOR_FIRING if notification.kind == KIND_FIRING else _COLOR_CALM
    return {
        "text": notification.text,
        "attachments": [
            {
                "color": color,
                "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": notification.text}}],
            }
        ],
    }


async def send(config: dict, notification: Notification, client: httpx.AsyncClient) -> None:
    await post_json(client, config["webhook_url"], build_payload(notification), "slack")
