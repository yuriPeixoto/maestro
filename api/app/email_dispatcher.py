from __future__ import annotations

from email.mime.text import MIMEText

import aiosmtplib
import httpx

from app.config import settings
from app.delivery import DeliveryFailed, Notification

_SUBJECT_MAX_CHARS = 120


def is_configured() -> bool:
    return bool(settings.smtp_host)


async def send(config: dict, notification: Notification, _client: httpx.AsyncClient) -> None:
    if not is_configured():
        raise DeliveryFailed("SMTP not configured")

    msg = MIMEText(notification.text, "plain", "utf-8")
    # A grouped message has several lines; a header holds one.
    msg["Subject"] = f"[Maestro] {notification.text.splitlines()[0]}"[:_SUBJECT_MAX_CHARS]
    msg["From"] = settings.smtp_from
    msg["To"] = config["to"]
    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            use_tls=settings.smtp_tls,
        )
    except Exception as exc:
        raise DeliveryFailed(type(exc).__name__) from None
