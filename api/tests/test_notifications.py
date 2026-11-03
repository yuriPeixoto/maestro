"""
Notification texts, channel delivery and the history of what was sent.

HTTP channels run against httpx.MockTransport, so these tests see the request
each channel would send and how a refusal is reported.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest

from app import notification_text, telegram_dispatcher
from app.clickhouse import SERVER_WIDE_RULE_ID, AlertChannel, AlertEvent
from app.delivery import KIND_FIRING, KIND_TEST, DeliveryFailed, Notification
from app.notification_dispatcher import available_channel_types, dispatch_all
from app.rule_values import HEARTBEAT_AGE_METRIC

_TOKEN = "123456:secret-token"
_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def _event(metric: str = "cpu_usage_percent", value: float = 92.34, state: str = "FIRING",
           threshold: float = 80.0, severity: str = "critical") -> AlertEvent:
    return AlertEvent(
        event_id=uuid4(), rule_id=uuid4(), server_id="web-1", metric_name=metric,
        value=value, threshold=threshold, severity=severity, state=state, triggered_at=_NOW,
    )


def _channel(channel_type: str, config: dict, rule_id=SERVER_WIDE_RULE_ID) -> AlertChannel:
    return AlertChannel(
        channel_id=uuid4(), rule_id=rule_id, server_id="web-1", channel_type=channel_type,
        config=json.dumps(config), enabled=True, created_at=_NOW,
    )


class _Writer:
    def __init__(self) -> None:
        self.records: list = []

    async def insert_notification_records(self, records) -> None:
        self.records.extend(records)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
def telegram(monkeypatch):
    monkeypatch.setattr(telegram_dispatcher.settings, "telegram_bot_token", _TOKEN)
    monkeypatch.setattr(telegram_dispatcher.settings, "telegram_default_chat_id", "-100200")


class TestText:
    def test_firing_text_is_portuguese_with_decimal_comma(self):
        text = notification_text.alert_text(_event())

        assert text == "🔴 Crítico em web-1: CPU (média de 5 min) em 92,3% (limite 80%)"
        assert "FIRING" not in text

    def test_resolved_text(self):
        text = notification_text.alert_text(_event(state="RESOLVED", value=40.0))

        assert text.startswith("🟢 Normalizou em web-1: CPU")
        assert "RESOLVED" not in text

    def test_offline_text_counts_minutes(self):
        text = notification_text.alert_text(_event(metric=HEARTBEAT_AGE_METRIC, value=310, threshold=90))

        assert text == "🔴 Crítico em web-1: sem sinal há 5 min"

    def test_back_online_text(self):
        text = notification_text.alert_text(_event(metric=HEARTBEAT_AGE_METRIC, value=10, state="RESOLVED"))

        assert text == "🟢 Normalizou em web-1: voltou a enviar sinal"

    def test_english_when_configured(self, monkeypatch):
        monkeypatch.setattr(notification_text.settings, "notification_language", "en")

        assert notification_text.alert_text(_event(metric="disk_usage_percent", value=96, threshold=95)) == (
            "🔴 Critical on web-1: Disk at 96% (limit 95%)"
        )


class TestTelegram:
    @pytest.mark.asyncio
    async def test_sends_to_the_default_chat(self, telegram):
        sent: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return httpx.Response(200, json={"ok": True})

        notification = Notification(kind=KIND_TEST, server_id="web-1", text="olá")
        async with _client(handler) as client:
            await telegram_dispatcher.send({}, notification, client)

        assert sent[0].url.path == f"/bot{_TOKEN}/sendMessage"
        assert json.loads(sent[0].content) == {"chat_id": "-100200", "text": "olá", "disable_web_page_preview": True}

    @pytest.mark.asyncio
    async def test_refusal_reason_never_holds_the_token(self, telegram):
        def handler(_request):
            return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})

        notification = Notification(kind=KIND_TEST, server_id="web-1", text="olá")
        async with _client(handler) as client:
            with pytest.raises(DeliveryFailed) as caught:
                await telegram_dispatcher.send({"chat_id": "42"}, notification, client)

        assert caught.value.reason == "HTTP 400: Bad Request: chat not found"
        assert _TOKEN not in str(caught.value)

    @pytest.mark.asyncio
    async def test_not_offered_without_a_token(self, monkeypatch):
        monkeypatch.setattr(telegram_dispatcher.settings, "telegram_bot_token", "")

        assert "telegram" not in available_channel_types()


class TestDispatchAll:
    @pytest.mark.asyncio
    async def test_records_each_delivery_with_its_outcome(self, telegram):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "hooks.example.com":
                return httpx.Response(404)
            return httpx.Response(200, json={"ok": True})

        event = _event()
        notification = Notification(kind=KIND_FIRING, server_id="web-1", text="x", event=event)
        channels = [_channel("telegram", {}), _channel("webhook", {"url": "https://hooks.example.com/secret"})]
        writer = _Writer()

        async with _client(handler) as client:
            results = await dispatch_all(channels, notification, writer, client)

        assert [(r.ok, r.error) for r in results] == [(True, ""), (False, "HTTP 404")]
        assert [(r.channel_type, r.ok, r.kind) for r in writer.records] == [
            ("telegram", True, "firing"), ("webhook", False, "firing"),
        ]
        assert writer.records[0].rule_id == event.rule_id
        assert writer.records[0].event_id == event.event_id

    @pytest.mark.asyncio
    async def test_webhook_payload_carries_the_text_and_the_event(self):
        bodies: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(204)

        event = _event()
        notification = Notification(kind=KIND_FIRING, server_id="web-1", text="🔴 alerta", event=event)
        async with _client(handler) as client:
            await dispatch_all([_channel("webhook", {"url": "https://h.example.com/x"})], notification, _Writer(), client)

        assert bodies[0]["text"] == "🔴 alerta"
        assert bodies[0]["kind"] == "firing"
        assert bodies[0]["rule_id"] == str(event.rule_id)
        assert bodies[0]["triggered_at"] == "2026-11-03T12:00:00Z"

    @pytest.mark.asyncio
    async def test_unknown_type_is_recorded_as_a_failure(self):
        writer = _Writer()
        notification = Notification(kind=KIND_TEST, server_id="web-1", text="x")

        async with _client(lambda _r: httpx.Response(200)) as client:
            [result] = await dispatch_all([_channel("pager", {})], notification, writer, client)

        assert not result.ok
        assert writer.records[0].ok is False
