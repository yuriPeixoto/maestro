from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app import email_dispatcher, slack_dispatcher, telegram_dispatcher, webhook_dispatcher
from app.clickhouse import AlertChannel, ClickHouseWriter, NotificationRecord
from app.delivery import HTTP_TIMEOUT_SECONDS, DeliveryFailed, Notification

logger = logging.getLogger(__name__)

Sender = Callable[[dict, Notification, httpx.AsyncClient], Awaitable[None]]

SENDERS: dict[str, Sender] = {
    "webhook": webhook_dispatcher.send,
    "slack": slack_dispatcher.send,
    "email": email_dispatcher.send,
    "telegram": telegram_dispatcher.send,
}

# Channel types that need server-side configuration before they can work.
_AVAILABILITY: dict[str, Callable[[], bool]] = {
    "email": email_dispatcher.is_configured,
    "telegram": telegram_dispatcher.is_configured,
}


def available_channel_types() -> list[str]:
    return [kind for kind in SENDERS if _AVAILABILITY.get(kind, lambda: True)()]


@dataclass(frozen=True)
class DeliveryResult:
    channel: AlertChannel
    ok: bool
    error: str


async def _deliver(channel: AlertChannel, notification: Notification, client: httpx.AsyncClient) -> DeliveryResult:
    sender = SENDERS.get(channel.channel_type)
    try:
        if sender is None:
            raise DeliveryFailed(f"unknown channel type {channel.channel_type}")
        try:
            config = json.loads(channel.config)
        except json.JSONDecodeError:
            raise DeliveryFailed("invalid channel config") from None
        await sender(config, notification, client)
    except DeliveryFailed as exc:
        logger.error("notification: %s channel %s failed: %s", channel.channel_type, channel.channel_id, exc.reason)
        return DeliveryResult(channel, ok=False, error=exc.reason)
    except Exception as exc:
        logger.exception("notification: %s channel %s raised", channel.channel_type, channel.channel_id)
        return DeliveryResult(channel, ok=False, error=type(exc).__name__)
    logger.info("notification: %s sent %s for %s", channel.channel_type, notification.kind, notification.server_id)
    return DeliveryResult(channel, ok=True, error="")


def _record(result: DeliveryResult, notification: Notification, sent_at: datetime) -> NotificationRecord:
    return NotificationRecord(
        sent_at=sent_at,
        server_id=notification.server_id,
        channel_id=result.channel.channel_id,
        channel_type=result.channel.channel_type,
        rule_id=notification.rule_id,
        event_id=notification.event_id,
        kind=notification.kind,
        ok=result.ok,
        error=result.error,
    )


async def dispatch_all(
    channels: list[AlertChannel],
    notification: Notification,
    writer: ClickHouseWriter,
    client: httpx.AsyncClient | None = None,
) -> list[DeliveryResult]:
    """Send to every enabled channel and store one history row per channel."""
    targets = [ch for ch in channels if ch.enabled]
    if not targets:
        return []

    if client is None:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as own_client:
            results = await asyncio.gather(*[_deliver(ch, notification, own_client) for ch in targets])
    else:
        results = await asyncio.gather(*[_deliver(ch, notification, client) for ch in targets])

    sent_at = datetime.now(timezone.utc)
    try:
        await writer.insert_notification_records([_record(r, notification, sent_at) for r in results])
    except Exception:
        logger.exception("notification: could not store the delivery history for %s", notification.server_id)
    return list(results)
