"""What the channels hear: the lines of one cycle, one message per server and channel.

A burst on one server (disk, memory and CPU crossing together, or every metric going
quiet at once) is one message with a line each, not one message per rule. A channel
gets only the lines of the rules it takes. A delivery that fails is kept for a retry
(app.notification_retries).
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from app import alert_store, notification_retries
from app.alert_store import AlertChannel
from app.clickhouse import ClickHouseWriter
from app.delivery import Line, Notification
from app.notification_dispatcher import dispatch_one
from app.notification_text import grouped_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Outgoing:
    line: Line
    group_id: int | None = None

    @property
    def server_id(self) -> str:
        return self.line.event.server_id


@dataclass(frozen=True)
class Message:
    channel: AlertChannel
    notification: Notification


def _takes(channel: AlertChannel, rule_id: UUID) -> bool:
    return channel.rule_id is None or channel.rule_id == rule_id


async def compose(outgoing: list[Outgoing], labels: dict[str, str] | None = None) -> list[Message]:
    """Group the lines by server and by the channels that take them, keeping their order."""
    labels = labels or {}
    by_server: dict[str, list[Outgoing]] = defaultdict(list)
    for item in outgoing:
        by_server[item.server_id].append(item)

    messages: list[Message] = []
    for server_id, items in by_server.items():
        channels = await alert_store.channels_reaching(server_id, items[0].group_id)
        for channel in channels:
            lines = [item.line for item in items if _takes(channel, item.line.event.rule_id)]
            if not lines:
                continue
            text = grouped_text(server_id, [line.text for line in lines], labels.get(server_id))
            messages.append(Message(channel, Notification.of_lines(server_id, lines, text)))
    return messages


async def deliver(messages: list[Message], writer: ClickHouseWriter) -> None:
    async def one(message: Message) -> None:
        result = await dispatch_one(message.channel, message.notification, writer)
        if not result.ok:
            await notification_retries.schedule(message.channel.channel_id, message.notification, result.error)

    outcomes = await asyncio.gather(*[one(m) for m in messages], return_exceptions=True)
    for message, outcome in zip(messages, outcomes):
        if isinstance(outcome, BaseException):
            logger.error(
                "notification: could not deliver or keep for retry (%s channel %s): %s",
                message.channel.channel_type, message.channel.channel_id, outcome,
            )


async def send(outgoing: list[Outgoing], writer: ClickHouseWriter, labels: dict[str, str] | None = None) -> None:
    if outgoing:
        await deliver(await compose(outgoing, labels), writer)


# Deliveries run beside the evaluation so a slow channel does not hold the cycle.
# The set keeps a reference until each one finishes.
_deliveries: set[asyncio.Task] = set()


def send_soon(outgoing: list[Outgoing], writer: ClickHouseWriter, labels: dict[str, str] | None = None) -> None:
    if not outgoing:
        return
    task = asyncio.create_task(send(list(outgoing), writer, labels))
    _deliveries.add(task)
    task.add_done_callback(_finished)


def _finished(task: asyncio.Task) -> None:
    _deliveries.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error("notification: a delivery pass failed: %s", task.exception())
