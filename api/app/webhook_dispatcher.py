from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from app.clickhouse import AlertEvent

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_BASE_DELAY = 1.0  # seconds


def _build_payload(event: AlertEvent) -> dict:
    triggered_at = event.triggered_at
    if isinstance(triggered_at, datetime):
        ts = triggered_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    else:
        ts = str(triggered_at)

    icon = "🔴" if event.state == "FIRING" else "🟢"
    text = (
        f"{icon} {event.state}: {event.metric_name} {_op_symbol(event)} {event.threshold}"
        f" em {event.server_id} (valor: {event.value:.2f})"
    )

    return {
        "text": text,
        "server_id": event.server_id,
        "metric_name": event.metric_name,
        "value": event.value,
        "threshold": event.threshold,
        "severity": event.severity,
        "state": event.state,
        "triggered_at": ts,
    }


def _op_symbol(event: AlertEvent) -> str:
    # We don't store the operator on the event, so we infer direction from state context.
    # The text is descriptive enough without it.
    return "≠"


async def dispatch(url: str, event: AlertEvent) -> None:
    payload = _build_payload(event)
    delay = _BASE_DELAY
    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                logger.info(
                    "webhook: dispatched %s for rule=%s to %s (HTTP %d)",
                    event.state, event.rule_id, url, resp.status_code,
                )
                return
            except Exception as exc:
                if attempt == _MAX_ATTEMPTS:
                    logger.error(
                        "webhook: failed after %d attempts for rule=%s: %s",
                        _MAX_ATTEMPTS, event.rule_id, exc,
                    )
                    return
                logger.warning(
                    "webhook: attempt %d/%d failed for rule=%s: %s — retrying in %.1fs",
                    attempt, _MAX_ATTEMPTS, event.rule_id, exc, delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
