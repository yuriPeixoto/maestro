from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app import email_dispatcher, slack_dispatcher, telegram_dispatcher, webhook_dispatcher
from app.alert_store import AlertChannel
from app.clickhouse import ClickHouseWriter, NotificationRecord
from app.delivery import HTTP_TIMEOUT_SECONDS, DeliveryFailed, Notification

logger = logging.getLogger(__name__)

Sender = Callable[[dict, Notification, httpx.AsyncClient], Awaitable[None]]

SENDERS: dict[str, Sender] = {
    "telegram": telegram_dispatcher.send,
    "webhook": webhook_dispatcher.send,
    "slack": slack_dispatcher.send,
    "email": email_dispatcher.send,
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
        await sender(channel.config, notification, client)
    except DeliveryFailed as exc:
        logger.error("notification: %s channel %s failed: %s", channel.channel_type, channel.channel_id, exc.reason)
        return DeliveryResult(channel, ok=False, error=exc.reason)
    except Exception as exc:
        logger.exception("notification: %s channel %s raised", channel.channel_type, channel.channel_id)
        return DeliveryResult(channel, ok=False, error=type(exc).__name__)
    logger.info("notification: %s sent %s for %s", channel.channel_type, notification.kind, notification.server_id)
    return DeliveryResult(channel, ok=True, error="")


def _records(result: DeliveryResult, notification: Notification, sent_at: datetime) -> list[NotificationRecord]:
    """One history row per line, so each alert's deliveries can be told apart; one for a test."""
    def record(kind: str, rule_id, event_id) -> NotificationRecord:
        return NotificationRecord(
            sent_at=sent_at,
            server_id=notification.server_id,
            channel_id=result.channel.channel_id,
            channel_type=result.channel.channel_type,
            rule_id=rule_id,
            event_id=event_id,
            kind=kind,
            ok=result.ok,
            error=result.error,
        )

    if not notification.lines:
        return [record(notification.kind, notification.rule_id, notification.event_id)]
    return [record(line.kind, line.event.rule_id, line.event.event_id) for line in notification.lines]


async def dispatch_one(
    channel: AlertChannel,
    notification: Notification,
    writer: ClickHouseWriter,
    client: httpx.AsyncClient | None = None,
) -> DeliveryResult:
    [result] = await dispatch_all([channel], notification, writer, client)
    return result


async def dispatch_all(
    channels: list[AlertChannel],
    notification: Notification,
    writer: ClickHouseWriter,
    client: httpx.AsyncClient | None = None,
) -> list[DeliveryResult]:
    """Send to every channel and store one history row per channel."""
    targets = list(channels)
    if not targets:
        return []

    if client is None:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as own_client:
            results = await asyncio.gather(*[_deliver(ch, notification, own_client) for ch in targets])
    else:
        results = await asyncio.gather(*[_deliver(ch, notification, client) for ch in targets])

    sent_at = datetime.now(timezone.utc)
    try:
        await writer.insert_notification_records(
            [record for r in results for record in _records(r, notification, sent_at)],
        )
    except Exception:
        logger.exception("notification: could not store the delivery history for %s", notification.server_id)
    return list(results)
