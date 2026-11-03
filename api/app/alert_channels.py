"""Notification channels of a server, one list for every type.

A channel either takes every rule of its server (`rule_id` null in the API,
SERVER_WIDE_RULE_ID in storage) or a single rule.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field, HttpUrl, ValidationError

from app.clickhouse import SERVER_WIDE_RULE_ID, AlertChannel, ClickHouseReader, ClickHouseWriter
from app.delivery import KIND_TEST, Notification
from app.logs import _utc_iso
from app.notification_dispatcher import available_channel_types, dispatch_all
from app.notification_text import channel_test_text
from app.telegram_dispatcher import resolve_chat_id

router = APIRouter(prefix="/alerts", tags=["alerts"])

_HISTORY_DEFAULT_LIMIT = 50
_HISTORY_MAX_LIMIT = 200
_URL_TAIL_CHARS = 4


# ── Config per channel type ───────────────────────────────────────────────────

class _WebhookConfig(BaseModel):
    url: HttpUrl


class _SlackConfig(BaseModel):
    webhook_url: HttpUrl


class _EmailConfig(BaseModel):
    to: EmailStr


class _TelegramConfig(BaseModel):
    chat_id: str = Field(default="", max_length=64)


_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "webhook": _WebhookConfig,
    "slack": _SlackConfig,
    "email": _EmailConfig,
    "telegram": _TelegramConfig,
}


def _validated_config(channel_type: str, config: dict) -> dict:
    try:
        return _CONFIG_MODELS[channel_type](**config).model_dump(mode="json")
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False, include_context=False)) from None


def _mask_url(url: str) -> str:
    """Show where a URL points without the path, which often is the secret."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/…{url[-_URL_TAIL_CHARS:]}"


def _mask_config(channel_type: str, cfg: dict) -> dict:
    """Remove sensitive fields before returning config to the client."""
    safe = dict(cfg)
    if channel_type == "email" and "to" in safe:
        at = safe["to"].find("@")
        safe["to"] = safe["to"][:2] + "***" + safe["to"][at:]
    elif channel_type == "webhook" and "url" in safe:
        safe["url"] = _mask_url(safe["url"])
    elif channel_type == "slack" and "webhook_url" in safe:
        safe["webhook_url"] = _mask_url(safe["webhook_url"])
    elif channel_type == "telegram":
        safe["uses_default_chat"] = not safe.get("chat_id")
        safe["chat_id"] = resolve_chat_id(safe)
    return safe


# ── Models ────────────────────────────────────────────────────────────────────

class ChannelTypesOut(BaseModel):
    types: list[str]


class ChannelIn(BaseModel):
    channel_type: str = Field(pattern=r"^(webhook|email|slack|telegram)$")
    config: dict = Field(default_factory=dict)
    rule_id: UUID | None = None   # None: every rule of the server


class ChannelOut(BaseModel):
    channel_id: str
    rule_id: str | None
    channel_type: str
    config: dict
    created_at: str


class DeliveryOut(BaseModel):
    ok: bool
    error: str


class NotificationOut(BaseModel):
    sent_at: str
    channel_id: str
    channel_type: str
    rule_id: str | None
    kind: str
    ok: bool
    error: str


def _channel_out(ch: AlertChannel) -> ChannelOut:
    return ChannelOut(
        channel_id=str(ch.channel_id),
        rule_id=None if ch.rule_id == SERVER_WIDE_RULE_ID else str(ch.rule_id),
        channel_type=ch.channel_type,
        config=_mask_config(ch.channel_type, json.loads(ch.config)),
        created_at=_utc_iso(ch.created_at),
    )


async def _server_channel(reader: ClickHouseReader, server_id: str, channel_id: UUID) -> AlertChannel:
    channels = await reader.get_channels_for_server(server_id)
    channel = next((ch for ch in channels if ch.channel_id == channel_id), None)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/channel-types", response_model=ChannelTypesOut)
async def get_channel_types() -> ChannelTypesOut:
    """Types this installation can deliver; Telegram and e-mail need server settings."""
    return ChannelTypesOut(types=available_channel_types())


@router.get("/{server_id}/channels", response_model=list[ChannelOut])
async def list_channels(server_id: str, request: Request) -> list[ChannelOut]:
    reader: ClickHouseReader = request.app.state.ch_reader
    return [_channel_out(ch) for ch in await reader.get_channels_for_server(server_id)]


@router.post("/{server_id}/channels", response_model=ChannelOut, status_code=201)
async def add_channel(server_id: str, body: ChannelIn, request: Request) -> ChannelOut:
    writer: ClickHouseWriter = request.app.state.ch_writer
    reader: ClickHouseReader = request.app.state.ch_reader

    if body.channel_type not in available_channel_types():
        raise HTTPException(status_code=422, detail=f"Channel type '{body.channel_type}' is not configured")
    config = _validated_config(body.channel_type, body.config)
    if body.channel_type == "telegram" and not resolve_chat_id(config):
        raise HTTPException(status_code=422, detail="Telegram needs a chat_id: none given and no default configured")

    if body.rule_id is not None:
        rules = await reader.get_alert_rules(server_id)
        if not any(r.rule_id == body.rule_id for r in rules):
            raise HTTPException(status_code=404, detail="Rule not found")

    channel = AlertChannel(
        channel_id=uuid4(),
        rule_id=body.rule_id or SERVER_WIDE_RULE_ID,
        server_id=server_id,
        channel_type=body.channel_type,
        config=json.dumps(config),
        enabled=True,
        created_at=datetime.now(timezone.utc),
    )
    await writer.insert_alert_channel(channel)
    return _channel_out(channel)


@router.delete("/{server_id}/channels/{channel_id}", status_code=204)
async def delete_channel(server_id: str, channel_id: UUID, request: Request) -> Response:
    reader: ClickHouseReader = request.app.state.ch_reader
    writer: ClickHouseWriter = request.app.state.ch_writer
    await _server_channel(reader, server_id, channel_id)
    await writer.delete_alert_channel(channel_id)
    return Response(status_code=204)


@router.post("/{server_id}/channels/{channel_id}/test", response_model=DeliveryOut)
async def test_channel(server_id: str, channel_id: UUID, request: Request) -> DeliveryOut:
    reader: ClickHouseReader = request.app.state.ch_reader
    writer: ClickHouseWriter = request.app.state.ch_writer
    channel = await _server_channel(reader, server_id, channel_id)
    notification = Notification(kind=KIND_TEST, server_id=server_id, text=channel_test_text(server_id))
    [result] = await dispatch_all([channel], notification, writer)
    return DeliveryOut(ok=result.ok, error=result.error)


@router.get("/{server_id}/notifications", response_model=list[NotificationOut])
async def list_notifications(
    server_id: str, request: Request, limit: int = _HISTORY_DEFAULT_LIMIT,
) -> list[NotificationOut]:
    reader: ClickHouseReader = request.app.state.ch_reader
    records = await reader.get_notification_log(server_id, limit=min(max(limit, 1), _HISTORY_MAX_LIMIT))
    return [
        NotificationOut(
            sent_at=_utc_iso(r.sent_at),
            channel_id=str(r.channel_id),
            channel_type=r.channel_type,
            rule_id=None if r.rule_id == SERVER_WIDE_RULE_ID else str(r.rule_id),
            kind=r.kind,
            ok=r.ok,
            error=r.error,
        )
        for r in records
    ]
