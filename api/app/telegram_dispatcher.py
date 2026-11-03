"""Telegram Bot API channel.

The bot token comes from MAESTRO_TELEGRAM_BOT_TOKEN only, never from a channel's
stored config, so it is not in ClickHouse and never reaches the browser. A
channel may leave `chat_id` empty to use MAESTRO_TELEGRAM_DEFAULT_CHAT_ID.
"""
from __future__ import annotations

import httpx

from app.config import settings
from app.delivery import DeliveryFailed, Notification, post_json

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def is_configured() -> bool:
    return bool(settings.telegram_bot_token)


def resolve_chat_id(config: dict) -> str:
    return str(config.get("chat_id") or settings.telegram_default_chat_id or "").strip()


async def send(config: dict, notification: Notification, client: httpx.AsyncClient) -> None:
    if not is_configured():
        raise DeliveryFailed("Telegram bot token not configured")
    chat_id = resolve_chat_id(config)
    if not chat_id:
        raise DeliveryFailed("no chat_id")
    payload = {"chat_id": chat_id, "text": notification.text, "disable_web_page_preview": True}
    await post_json(client, _API_URL.format(token=settings.telegram_bot_token), payload, "telegram")
