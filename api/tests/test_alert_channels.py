"""
One channel list per server: add, mask, test, history; the legacy webhook moves in;
default rules; and an offline server notifying its channels.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import alert_evaluator, notification_dispatcher, telegram_dispatcher
from app.alert_channels import router
from app.clickhouse import SERVER_WIDE_RULE_ID, AlertRule
from app.config import settings
from app.default_rules import default_rules, ensure_default_rules
from app.rule_values import HEARTBEAT_AGE_METRIC

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


class _Store:
    """Reader and writer at once, over in-memory lists."""

    def __init__(self) -> None:
        self.channels: list = []
        self.rules: list[AlertRule] = []
        self.records: list = []
        self.events: list = []

    async def insert_alert_channel(self, channel) -> None:
        self.channels.append(channel)

    async def delete_alert_channel(self, channel_id: UUID) -> None:
        self.channels = [ch for ch in self.channels if ch.channel_id != channel_id]

    async def get_channels_for_server(self, server_id: str):
        return [ch for ch in self.channels if ch.server_id == server_id]

    async def get_channels_for_alert(self, server_id: str, rule_id: UUID):
        return [ch for ch in self.channels
                if ch.server_id == server_id and ch.rule_id in (rule_id, SERVER_WIDE_RULE_ID)]

    async def get_alert_rules(self, server_id: str):
        return [r for r in self.rules if r.server_id == server_id]

    async def insert_alert_rule(self, rule) -> None:
        self.rules.append(rule)

    async def insert_alert_event(self, event) -> None:
        self.events.append(event)

    async def insert_notification_records(self, records) -> None:
        self.records.extend(records)

    async def get_notification_log(self, server_id: str, limit: int = 50):
        return [r for r in reversed(self.records) if r.server_id == server_id][:limit]

    async def get_status_metric_value(self, _server_id, _metric):
        return None


@pytest.fixture
def store() -> _Store:
    return _Store()


@pytest.fixture
def client(store, monkeypatch) -> TestClient:
    monkeypatch.setattr(telegram_dispatcher.settings, "telegram_bot_token", "1:tok")
    monkeypatch.setattr(telegram_dispatcher.settings, "telegram_default_chat_id", "-100")
    app = FastAPI()
    app.include_router(router)
    app.state.ch_reader = store
    app.state.ch_writer = store
    return TestClient(app)


def _mock_http(monkeypatch, handler) -> None:
    real = httpx.AsyncClient

    def factory(*_args, **kwargs):
        return real(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(notification_dispatcher.httpx, "AsyncClient", factory)


class TestChannelRoutes:
    def test_types_include_telegram_but_not_email_without_smtp(self, client, monkeypatch):
        monkeypatch.setattr(settings, "smtp_host", "")

        assert client.get("/alerts/channel-types").json()["types"] == ["webhook", "slack", "telegram"]

    def test_server_wide_channel_lists_with_null_rule(self, client):
        created = client.post("/alerts/web-1/channels", json={"channel_type": "telegram"})

        assert created.status_code == 201
        listed = client.get("/alerts/web-1/channels").json()
        assert listed[0]["rule_id"] is None
        assert listed[0]["config"] == {"chat_id": "-100", "uses_default_chat": True}

    def test_webhook_url_is_masked(self, client):
        client.post("/alerts/web-1/channels",
                    json={"channel_type": "webhook", "config": {"url": "https://hooks.example.com/T0/B1/abcdsecret"}})

        url = client.get("/alerts/web-1/channels").json()[0]["config"]["url"]
        assert url == "https://hooks.example.com/…cret"

    def test_invalid_config_is_rejected(self, client):
        resp = client.post("/alerts/web-1/channels", json={"channel_type": "webhook", "config": {"url": "nope"}})

        assert resp.status_code == 422

    def test_channel_for_an_unknown_rule_is_rejected(self, client):
        resp = client.post("/alerts/web-1/channels", json={"channel_type": "telegram", "rule_id": str(uuid4())})

        assert resp.status_code == 404

    def test_unconfigured_type_is_rejected(self, client, monkeypatch):
        monkeypatch.setattr(settings, "smtp_host", "")

        resp = client.post("/alerts/web-1/channels", json={"channel_type": "email", "config": {"to": "a@b.com"}})

        assert resp.status_code == 422

    def test_test_send_reports_and_records_the_outcome(self, client, store, monkeypatch):
        _mock_http(monkeypatch, lambda _r: httpx.Response(403, json={"description": "Forbidden: bot was blocked"}))
        channel_id = client.post("/alerts/web-1/channels", json={"channel_type": "telegram"}).json()["channel_id"]

        resp = client.post(f"/alerts/web-1/channels/{channel_id}/test")

        assert resp.json() == {"ok": False, "error": "HTTP 403: Forbidden: bot was blocked"}
        history = client.get("/alerts/web-1/notifications").json()
        assert [(h["kind"], h["ok"], h["rule_id"]) for h in history] == [("test", False, None)]

    def test_channel_of_another_server_is_not_found(self, client):
        channel_id = client.post("/alerts/web-1/channels", json={"channel_type": "telegram"}).json()["channel_id"]

        assert client.post(f"/alerts/web-2/channels/{channel_id}/test").status_code == 404
        assert client.delete(f"/alerts/web-2/channels/{channel_id}").status_code == 404
        assert client.delete(f"/alerts/web-1/channels/{channel_id}").status_code == 204


class _Redis:
    def __init__(self, strings: dict | None = None, hashes: dict | None = None) -> None:
        self.strings = dict(strings or {})
        self.hashes = hashes or {}
        self.sets: dict[str, set] = {}

    async def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        for key in list(self.strings):
            if key.startswith(prefix):
                yield key

    async def get(self, key):
        return self.strings.get(key)

    async def set(self, key, value):
        self.strings[key] = value

    async def delete(self, key):
        self.strings.pop(key, None)

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    async def hkeys(self, key):
        return list(self.hashes.get(key, {}))

    async def sismember(self, key, member):
        return member in self.sets.get(key, set())

    async def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)


class TestLegacyWebhook:
    @pytest.mark.asyncio
    async def test_becomes_a_server_wide_channel_and_leaves_redis(self, store):
        redis = _Redis({"maestro:webhook:web-1": "https://hooks.example.com/x"})

        await alert_evaluator._migrate_legacy_webhooks(redis, store)

        [channel] = store.channels
        assert (channel.server_id, channel.rule_id, channel.channel_type) == ("web-1", SERVER_WIDE_RULE_ID, "webhook")
        assert json.loads(channel.config) == {"url": "https://hooks.example.com/x"}
        assert redis.strings == {}


class TestDefaultRules:
    def test_use_the_status_limits(self):
        rules = {(r.metric_name, r.severity): r for r in default_rules("web-1", _NOW)}

        assert rules[(HEARTBEAT_AGE_METRIC, "critical")].threshold == settings.offline_threshold_seconds
        assert rules[("disk_usage_percent", "warning")].threshold == settings.health_disk_attention_percent
        assert rules[("disk_usage_percent", "critical")].threshold == settings.health_disk_critical_percent
        assert rules[("memory_usage_percent", "critical")].threshold == settings.health_memory_critical_percent
        assert rules[("cpu_usage_percent", "critical")].threshold == settings.health_cpu_critical_percent

    @pytest.mark.asyncio
    async def test_created_once_for_a_server_without_rules(self, store):
        redis = _Redis()

        assert await ensure_default_rules("web-1", store, store, redis)
        store.rules.clear()  # the user deleted them all
        assert not await ensure_default_rules("web-1", store, store, redis)
        assert store.rules == []

    @pytest.mark.asyncio
    async def test_server_with_rules_keeps_its_own(self, store):
        store.rules = default_rules("web-1", _NOW)[:1]

        assert not await ensure_default_rules("web-1", store, store, _Redis())
        assert len(store.rules) == 1


class TestOfflineServerNotifies:
    @pytest.mark.asyncio
    async def test_silent_server_fires_its_offline_rule_on_server_wide_channels(self, store, monkeypatch):
        monkeypatch.setattr(telegram_dispatcher.settings, "telegram_bot_token", "1:tok")
        sent: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})

        _mock_http(monkeypatch, handler)
        last_seen = datetime.now(timezone.utc) - timedelta(minutes=10)
        redis = _Redis(hashes={settings.heartbeat_state_key: {"web-1": json.dumps({"last_seen": last_seen.isoformat()})}})
        await store.insert_alert_channel(alert_evaluator.AlertChannel(
            channel_id=uuid4(), rule_id=SERVER_WIDE_RULE_ID, server_id="web-1", channel_type="telegram",
            config=json.dumps({"chat_id": "42"}), enabled=True, created_at=_NOW,
        ))

        await alert_evaluator._evaluate_all(store, store, redis)
        for task in list(alert_evaluator._deliveries):
            await task

        assert [e.metric_name for e in store.events] == [HEARTBEAT_AGE_METRIC]
        assert sent[0]["chat_id"] == "42"
        assert sent[0]["text"] == "🔴 Crítico em web-1: sem sinal há 10 min"
        assert [(r.kind, r.ok) for r in store.records] == [("firing", True)]
