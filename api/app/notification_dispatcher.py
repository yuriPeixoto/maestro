from __future__ import annotations

import asyncio
import json
import logging

from app.clickhouse import AlertChannel, AlertEvent
from app.email_dispatcher import dispatch as email_dispatch
from app.slack_dispatcher import dispatch as slack_dispatch
from app.webhook_dispatcher import dispatch as webhook_dispatch

logger = logging.getLogger(__name__)


async def dispatch_all(channels: list[AlertChannel], event: AlertEvent) -> None:
    """Dispatch an alert event to all enabled channels for a rule."""
    if not channels:
        return

    tasks = []
    for ch in channels:
        if not ch.enabled:
            continue
        try:
            cfg = json.loads(ch.config)
        except json.JSONDecodeError:
            logger.error("notification: invalid JSON config for channel %s", ch.channel_id)
            continue

        if ch.channel_type == "webhook":
            url = cfg.get("url")
            if url:
                tasks.append(webhook_dispatch(url, event))
        elif ch.channel_type == "slack":
            url = cfg.get("webhook_url")
            if url:
                tasks.append(slack_dispatch(url, event))
        elif ch.channel_type == "email":
            to = cfg.get("to")
            if to:
                tasks.append(email_dispatch(to, event))
        else:
            logger.warning("notification: unknown channel_type '%s' for channel %s", ch.channel_type, ch.channel_id)

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("notification: channel dispatch %d raised: %s", i, result)
