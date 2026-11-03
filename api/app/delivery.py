"""What every notification channel sends and how a delivery fails.

A failure reason is shown on the channel screen and stored in the history, so
it never carries the exception text: an HTTP error message includes the URL,
and Slack and Telegram URLs hold the channel's secret.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID

import httpx

from app.clickhouse import AlertEvent

logger = logging.getLogger(__name__)

KIND_FIRING = "firing"
KIND_RESOLVED = "resolved"
KIND_TEST = "test"

NO_ID = UUID(int=0)

_MAX_ATTEMPTS = 3
_BASE_DELAY_SECONDS = 1.0
HTTP_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class Notification:
    kind: str
    server_id: str
    text: str
    event: AlertEvent | None = None

    @property
    def rule_id(self) -> UUID:
        return self.event.rule_id if self.event else NO_ID

    @property
    def event_id(self) -> UUID:
        return self.event.event_id if self.event else NO_ID


class DeliveryFailed(Exception):
    """The channel did not accept the notification. `reason` is safe to show."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_DETAIL_MAX_CHARS = 120


def _response_detail(resp: httpx.Response) -> str | None:
    """Telegram explains a refusal in `description` ("chat not found")."""
    try:
        body = resp.json()
    except ValueError:
        return None
    detail = body.get("description") if isinstance(body, dict) else None
    return detail[:_DETAIL_MAX_CHARS] if isinstance(detail, str) else None


def describe_http_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        detail = _response_detail(exc.response)
        status = f"HTTP {exc.response.status_code}"
        return f"{status}: {detail}" if detail else status
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPError):
        return "connection failed"
    return type(exc).__name__


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    channel_type: str,
    sleep=asyncio.sleep,
) -> httpx.Response:
    """POST with retries; raise DeliveryFailed with a reason that holds no URL."""
    delay = _BASE_DELAY_SECONDS
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            # A 4xx will not change on retry: bad URL, revoked token, unknown chat.
            if exc.response.status_code < 500 or attempt == _MAX_ATTEMPTS:
                raise DeliveryFailed(describe_http_error(exc)) from None
            reason = describe_http_error(exc)
        except Exception as exc:
            if attempt == _MAX_ATTEMPTS:
                raise DeliveryFailed(describe_http_error(exc)) from None
            reason = describe_http_error(exc)
        logger.warning("%s: attempt %d/%d failed (%s) — retrying in %.1fs",
                       channel_type, attempt, _MAX_ATTEMPTS, reason, delay)
        await sleep(delay)
        delay *= 2
    raise AssertionError("unreachable")
