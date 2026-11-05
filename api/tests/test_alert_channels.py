"""
One channel list per server: add, mask, test, history; default rules; and an
offline server notifying its channels. Channels and rules live in Postgres.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import alert_evaluator, alert_store, notification_dispatcher, telegram_dispatcher
from app.alert_channels import router
from app.alert_store import AlertChannel
from app.config import settings
from app.default_rules import default_rules, ensure_default_rules
from app.rule_values import HEARTBEAT_AGE_METRIC

_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


class _ClickHouse:
    """Reader and writer of the history, over in-memory lists."""

    def __init__(self) -> None:
        self.records: list = []
        self.events: list = []

    async def insert_alert_event(self, event) -> None:
        self.events.append(event)

    async def insert_notification_records(self, records) -> None:
        self.records.extend(records)

    async def get_notification_log(self, server_id: str, limit: int = 50):
        return [r for r in reversed(self.records) if r.server_id == server_id][:limit]

    async def get_status_metric_value(self, _server_id, _metric):
        return None

    async def get_latest_anomaly_score(self, _server_id, _metric):
        return None


class _Redis:
    def __init__(self, hashes: dict | None = None) -> None:
        self.hashes = hashes or {}

    async def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    async def hkeys(self, key):
        return list(self.hashes.get(key, {}))


@pytest.fixture
def clickhouse() -> _ClickHouse:
    return _ClickHouse()


@pytest.fixture
def client(postgres, clickhouse, monkeypatch) -> TestClient:
    monkeypatch.setattr(telegram_dispatcher.settings, "telegram_bot_token", "1:tok")
    monkeypatch.setattr(telegram_dispatcher.settings, "telegram_default_chat_id", "-100")
    app = FastAPI()
    app.include_router(router)
    app.state.ch_reader = clickhouse
    app.state.ch_writer = clickhouse
    return TestClient(app)


def _mock_http(monkeypatch, handler) -> None:
    real = httpx.AsyncClient

    def factory(*_args, **kwargs):
        return real(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout"))

    monkeypatch.setattr(notification_dispatcher.httpx, "AsyncClient", factory)


class TestChannelRoutes:
    def test_types_include_telegram_but_not_email_without_smtp(self, client, monkeypatch):
        monkeypatch.setattr(settings, "smtp_host", "")

        assert client.get("/alerts/channel-types").json()["types"] == ["telegram", "webhook", "slack"]

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

    @pytest.mark.asyncio
    async def test_channel_for_another_servers_rule_is_rejected(self, client):
        [rule] = default_rules("web-2", _NOW)[:1]
        await alert_store.create_rule(rule)

        resp = client.post("/alerts/web-1/channels", json={"channel_type": "telegram", "rule_id": str(rule.rule_id)})

        assert resp.status_code == 404

    def test_unconfigured_type_is_rejected(self, client, monkeypatch):
        monkeypatch.setattr(settings, "smtp_host", "")

        resp = client.post("/alerts/web-1/channels", json={"channel_type": "email", "config": {"to": "a@b.com"}})

        assert resp.status_code == 422

    def test_test_send_reports_and_records_the_outcome(self, client, monkeypatch):
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
        assert client.get("/alerts/web-1/channels").json() == []
        assert client.delete(f"/alerts/web-1/channels/{channel_id}").status_code == 404


class TestDefaultRules:
    def test_use_the_status_limits(self):
        rules = {(r.metric_name, r.severity): r for r in default_rules("web-1", _NOW)}

        assert rules[(HEARTBEAT_AGE_METRIC, "critical")].threshold == settings.offline_threshold_seconds
        assert rules[("disk_usage_percent", "warning")].threshold == settings.health_disk_attention_percent
        assert rules[("disk_usage_percent", "critical")].threshold == settings.health_disk_critical_percent
        assert rules[("memory_usage_percent", "critical")].threshold == settings.health_memory_critical_percent
        assert rules[("cpu_usage_percent", "critical")].threshold == settings.health_cpu_critical_percent

    @pytest.mark.asyncio
    async def test_created_once_for_a_server_without_rules(self, postgres):
        assert await ensure_default_rules("web-1")
        rules = await alert_store.list_rules("web-1")
        assert len(rules) == 5
        for rule in rules:  # the user deleted them all
            await alert_store.delete_rule("web-1", rule.rule_id)

        assert not await ensure_default_rules("web-1")
        assert await alert_store.list_rules("web-1") == []
        assert await alert_store.servers_with_defaults() == {"web-1"}

    @pytest.mark.asyncio
    async def test_server_with_rules_keeps_its_own(self, postgres):
        await alert_store.create_rule(default_rules("web-1", _NOW)[0])

        assert not await ensure_default_rules("web-1")
        assert len(await alert_store.list_rules("web-1")) == 1


class TestOfflineServerNotifies:
    @pytest.mark.asyncio
    async def test_silent_server_fires_its_offline_rule_on_server_wide_channels(self, postgres, monkeypatch):
        monkeypatch.setattr(telegram_dispatcher.settings, "telegram_bot_token", "1:tok")
        sent: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})

        _mock_http(monkeypatch, handler)
        clickhouse = _ClickHouse()
        last_seen = datetime.now(timezone.utc) - timedelta(minutes=10)
        redis = _Redis(hashes={settings.heartbeat_state_key: {"web-1": json.dumps({"last_seen": last_seen.isoformat()})}})
        await alert_store.create_channel(AlertChannel(
            channel_id=uuid4(), rule_id=None, server_id="web-1", channel_type="telegram",
            config={"chat_id": "42"}, created_at=_NOW,
        ))

        await alert_evaluator._evaluate_all(clickhouse, clickhouse, redis)
        for task in list(alert_evaluator._deliveries):
            await task

        assert [e.metric_name for e in clickhouse.events] == [HEARTBEAT_AGE_METRIC]
        assert sent[0]["chat_id"] == "42"
        assert sent[0]["text"] == "🔴 Crítico em web-1: sem sinal há 10 min"
        assert [(r.kind, r.ok) for r in clickhouse.records] == [("firing", True)]
        assert list((await alert_store.firing_severities("web-1")).values()) == ["critical"]
