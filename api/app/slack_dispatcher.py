from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from app.clickhouse import AlertEvent

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_BASE_DELAY = 1.0


def _build_blocks(event: AlertEvent) -> dict:
    is_firing = event.state == "FIRING"
    triggered_at = event.triggered_at
    if isinstance(triggered_at, datetime):
        ts = triggered_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    else:
        ts = str(triggered_at)

    icon = "🔴" if is_firing else "🟢"
    color = "#e53e3e" if is_firing else "#38a169"
    title = f"{icon} {event.state}: `{event.metric_name}` on `{event.server_id}`"

    return {
        "attachments": [
            {
                "color": color,
                "blocks": [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": title},
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Server*\n{event.server_id}"},
                            {"type": "mrkdwn", "text": f"*Metric*\n{event.metric_name}"},
                            {"type": "mrkdwn", "text": f"*Value*\n{event.value:.2f}"},
                            {"type": "mrkdwn", "text": f"*Threshold*\n{event.threshold}"},
                            {"type": "mrkdwn", "text": f"*Severity*\n{event.severity}"},
                            {"type": "mrkdwn", "text": f"*Time*\n{ts}"},
                        ],
                    },
                ],
            }
        ]
    }


async def dispatch(webhook_url: str, event: AlertEvent) -> None:
    payload = _build_blocks(event)
    delay = _BASE_DELAY
    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                resp = await client.post(webhook_url, json=payload)
                resp.raise_for_status()
                logger.info(
                    "slack: dispatched %s for rule=%s (HTTP %d)",
                    event.state, event.rule_id, resp.status_code,
                )
                return
            except Exception as exc:
                if attempt == _MAX_ATTEMPTS:
                    logger.error(
                        "slack: failed after %d attempts for rule=%s: %s",
                        _MAX_ATTEMPTS, event.rule_id, exc,
                    )
                    return
                logger.warning(
                    "slack: attempt %d/%d failed for rule=%s: %s — retrying in %.1fs",
                    attempt, _MAX_ATTEMPTS, event.rule_id, exc, delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
