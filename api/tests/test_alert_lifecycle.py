"""
The alert cycle (ADR-014): acknowledging, repeating, "no data", what is announced when a
silence or maintenance ends, ML rules judged on open episodes, one message per server
and channel, and failed deliveries retried with a growing wait and a limit.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import alert_evaluator, alert_outbox, alert_store, db, notification_dispatcher, notification_retries, server_store
from app.alert_outbox import Outgoing
from app.alert_store import (
    STATE_FIRING,
    STATE_NO_DATA,
    AlertChannel,
    AlertRule,
    AlreadyAcknowledged,
    NotOpen,
)
from app.clickhouse import AlertEvent
from app.delivery import (
    KIND_ACKNOWLEDGED,
    KIND_DATA_BACK,
    KIND_FIRING,
    KIND_GROUPED,
    KIND_NO_DATA,
    KIND_REMINDER,
    KIND_RESOLVED,
    Line,
    Notification,
)
from app.models import AuditLogRow, NotificationRetryRow
from app.notification_dispatcher import DeliveryResult
from app.notification_text import (
    acknowledged_text,
    alert_text,
    delayed_text,
    grouped_text,
    late_suffix,
    no_data_text,
    reminder_text,
)
from app.open_alerts import router
from app.quiet import QuietNow
from app.rule_scope import SCOPE_GLOBAL, SCOPE_SERVER
from tests.conftest import act_as

_UTC = timezone.utc
_SERVER = "web-1"


def _now() -> datetime:
    return datetime.now(_UTC)


class _ClickHouse:
    def __init__(self, value: float | None = None, seen: bool = True) -> None:
        self.value = value
        self.seen = seen
        self.episode_score: float | None = None
        self.latest_score: float | None = None
        self.events: list = []
        self.records: list = []

    async def get_status_metric_value(self, _server_id, _metric):
        return self.value

    async def get_latest_anomaly_score(self, _server_id, _metric):
        return self.latest_score

    async def get_open_episode_score(self, _server_id, _metric):
        return self.episode_score

    async def has_metric_since(self, _server_id, _metric, _since):
        return self.seen

    async def insert_alert_event(self, event) -> None:
        self.events.append(event)

    async def insert_notification_records(self, records) -> None:
        self.records.extend(records)


class _Redis:
    async def hget(self, _key, _field):
        return None


async def _user(user_id: int = 1, username: str = "ana") -> int:
    async with db.session() as s:
        await s.execute(text(
            "INSERT INTO users (id, username, email, password_hash) OVERRIDING SYSTEM VALUE"
            " VALUES (:id, :name, :email, 'x')"
        ), {"id": user_id, "name": username, "email": f"{username}@example.com"})
    return user_id


def _rule(metric: str = "cpu_usage_percent", cooldown: int = 15, mode: str = "static", scope: str = SCOPE_SERVER) -> AlertRule:
    return AlertRule(
        rule_id=uuid4(), server_id=_SERVER if scope == SCOPE_SERVER else None, metric_name=metric, operator=">=",
        threshold=90.0, severity="critical", cooldown_minutes=cooldown, created_at=_now(), alert_mode=mode,
        scope=scope,
    )


async def _item(rule_id):
    [item] = [i for i in await alert_store.rules_to_evaluate([_SERVER]) if i.rule.rule_id == rule_id]
    return item


async def _cycle_of(rule_id, clickhouse: _ClickHouse, quiet: QuietNow | None = None, offline: set[str] | None = None):
    """Judge one rule once; the lines it would send are in the returned cycle."""
    cycle = alert_evaluator._Cycle(quiet or QuietNow(), {}, offline or set())
    await alert_evaluator._evaluate_rule(await _item(rule_id), clickhouse, clickhouse, _Redis(), cycle)
    return cycle


def _kinds(cycle) -> list[str]:
    return [o.line.kind for o in cycle.outgoing]


async def _notified_long_ago(rule_id, minutes: int) -> None:
    async with db.session() as s:
        await s.execute(
            text("UPDATE alert_state SET last_notified_at = now() - make_interval(mins => :m) WHERE rule_id = :r"),
            {"m": minutes, "r": rule_id},
        )


_MAINTENANCE = QuietNow(in_maintenance={_SERVER})


class TestRepeatAndAcknowledge:
    @pytest.mark.asyncio
    async def test_a_firing_alert_repeats_after_its_interval_until_acknowledged(self, postgres):
        user = await _user()
        rule = await alert_store.create_rule(_rule(cooldown=15))
        clickhouse = _ClickHouse(value=95.0)

        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == [KIND_FIRING]
        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == []          # within 15 min
        await _notified_long_ago(rule.rule_id, 16)
        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == [KIND_REMINDER]
        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == []          # the reminder restarts the wait

        await alert_store.acknowledge(rule.rule_id, _SERVER, user)
        await _notified_long_ago(rule.rule_id, 60)
        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == []
        state = (await _item(rule.rule_id)).state
        assert (state.state, state.acknowledged_by) == (STATE_FIRING, user)  # seen, still open

    @pytest.mark.asyncio
    async def test_resolving_drops_the_acknowledgement_so_the_next_alert_repeats_again(self, postgres):
        user = await _user()
        rule = await alert_store.create_rule(_rule(cooldown=0))
        clickhouse = _ClickHouse(value=95.0)
        await _cycle_of(rule.rule_id, clickhouse)
        await alert_store.acknowledge(rule.rule_id, _SERVER, user)

        clickhouse.value = 50.0
        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == [KIND_RESOLVED]

        state = (await _item(rule.rule_id)).state
        assert (state.acknowledged_at, state.acknowledged_by) == (None, None)

    @pytest.mark.asyncio
    async def test_no_reminder_while_quiet_then_one_as_soon_as_the_quiet_ends(self, postgres):
        rule = await alert_store.create_rule(_rule(cooldown=15))
        clickhouse = _ClickHouse(value=95.0)
        await _cycle_of(rule.rule_id, clickhouse)
        await _notified_long_ago(rule.rule_id, 40)

        assert _kinds(await _cycle_of(rule.rule_id, clickhouse, quiet=_MAINTENANCE)) == []
        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == [KIND_REMINDER]

    @pytest.mark.asyncio
    async def test_only_an_open_alert_is_acknowledged_and_only_once(self, postgres):
        user = await _user()
        rule = await alert_store.create_rule(_rule())

        with pytest.raises(NotOpen):
            await alert_store.acknowledge(rule.rule_id, _SERVER, user)
        await _cycle_of(rule.rule_id, _ClickHouse(value=95.0))
        await alert_store.acknowledge(rule.rule_id, _SERVER, user)
        with pytest.raises(AlreadyAcknowledged):
            await alert_store.acknowledge(rule.rule_id, _SERVER, user)


class TestNoData:
    @pytest.mark.asyncio
    async def test_a_metric_that_stops_goes_to_no_data_and_says_so_once(self, postgres):
        rule = await alert_store.create_rule(_rule())
        clickhouse = _ClickHouse(value=95.0)
        await _cycle_of(rule.rule_id, clickhouse)

        clickhouse.value = None
        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == [KIND_NO_DATA]
        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == []

        assert (await _item(rule.rule_id)).state.state == STATE_NO_DATA
        assert [e.state for e in clickhouse.events] == [STATE_FIRING, STATE_NO_DATA]

    @pytest.mark.asyncio
    async def test_a_calm_rule_also_goes_to_no_data_instead_of_keeping_its_state(self, postgres):
        rule = await alert_store.create_rule(_rule())

        cycle = await _cycle_of(rule.rule_id, _ClickHouse(value=None))

        assert _kinds(cycle) == [KIND_NO_DATA]
        assert (await _item(rule.rule_id)).state.state == STATE_NO_DATA

    @pytest.mark.asyncio
    async def test_a_metric_never_collected_is_left_alone(self, postgres):
        rule = await alert_store.create_rule(_rule(metric="typo_percent"))

        cycle = await _cycle_of(rule.rule_id, _ClickHouse(value=None, seen=False))

        assert _kinds(cycle) == []
        assert (await _item(rule.rule_id)).state.state == "INACTIVE"

    @pytest.mark.asyncio
    async def test_data_coming_back_is_announced_and_judged_again(self, postgres):
        rule = await alert_store.create_rule(_rule())
        clickhouse = _ClickHouse(value=None)
        await _cycle_of(rule.rule_id, clickhouse)

        clickhouse.value = 50.0
        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == [KIND_DATA_BACK]
        clickhouse.value = None
        await _cycle_of(rule.rule_id, clickhouse)
        clickhouse.value = 95.0
        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == [KIND_FIRING]

    @pytest.mark.asyncio
    async def test_a_server_without_signal_does_not_send_no_data_nor_its_return(self, postgres):
        rule = await alert_store.create_rule(_rule())
        clickhouse = _ClickHouse(value=None)

        assert _kinds(await _cycle_of(rule.rule_id, clickhouse, offline={_SERVER})) == []
        assert (await _item(rule.rule_id)).state.state == STATE_NO_DATA
        clickhouse.value = 50.0
        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == []  # the chat never heard it was missing


class TestQuietEnds:
    @pytest.mark.asyncio
    async def test_an_alert_that_fired_during_maintenance_is_announced_when_it_ends(self, postgres):
        rule = await alert_store.create_rule(_rule())
        clickhouse = _ClickHouse(value=95.0)

        assert _kinds(await _cycle_of(rule.rule_id, clickhouse, quiet=_MAINTENANCE)) == []
        cycle = await _cycle_of(rule.rule_id, clickhouse)

        assert _kinds(cycle) == [KIND_FIRING]
        assert "silêncio ou manutenção" in cycle.outgoing[0].line.text or "silence or maintenance" in cycle.outgoing[0].line.text

    @pytest.mark.asyncio
    async def test_a_resolution_during_a_silence_is_announced_when_it_ends(self, postgres):
        rule = await alert_store.create_rule(_rule())
        clickhouse = _ClickHouse(value=95.0)
        await _cycle_of(rule.rule_id, clickhouse)

        clickhouse.value = 50.0
        assert _kinds(await _cycle_of(rule.rule_id, clickhouse, quiet=_MAINTENANCE)) == []
        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == [KIND_RESOLVED]

    @pytest.mark.asyncio
    async def test_an_alert_that_came_and_went_during_the_quiet_says_nothing(self, postgres):
        rule = await alert_store.create_rule(_rule(cooldown=0))
        clickhouse = _ClickHouse(value=95.0)
        await _cycle_of(rule.rule_id, clickhouse, quiet=_MAINTENANCE)
        clickhouse.value = 50.0
        await _cycle_of(rule.rule_id, clickhouse, quiet=_MAINTENANCE)

        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == []


class TestOnceWithTwoEvaluators:
    @pytest.mark.asyncio
    async def test_a_reminder_read_twice_is_queued_once(self, postgres):
        rule = await alert_store.create_rule(_rule(cooldown=15))
        clickhouse = _ClickHouse(value=95.0)
        await _cycle_of(rule.rule_id, clickhouse)
        await _notified_long_ago(rule.rule_id, 16)
        stale = await _item(rule.rule_id)
        first, second = alert_evaluator._Cycle(), alert_evaluator._Cycle()

        await alert_evaluator._evaluate_rule(stale, clickhouse, clickhouse, _Redis(), first)
        await alert_evaluator._evaluate_rule(stale, clickhouse, clickhouse, _Redis(), second)

        assert (_kinds(first), _kinds(second)) == ([KIND_REMINDER], [])


class TestMachineLearningMode:
    @pytest.mark.asyncio
    async def test_fires_on_an_open_episode_that_includes_the_metric(self, postgres):
        rule = await alert_store.create_rule(_rule(mode="ml"))
        clickhouse = _ClickHouse(value=10.0)
        clickhouse.latest_score, clickhouse.episode_score = 0.9, 0.8

        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == [KIND_FIRING]

    @pytest.mark.asyncio
    async def test_one_anomalous_minute_without_an_episode_does_not_fire(self, postgres):
        rule = await alert_store.create_rule(_rule(mode="ml"))
        clickhouse = _ClickHouse(value=95.0)
        clickhouse.latest_score = 0.95  # the last minute scored high: 0.2.0 fired on this

        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == []

    @pytest.mark.asyncio
    async def test_an_episode_where_the_metric_barely_strays_does_not_fire(self, postgres):
        rule = await alert_store.create_rule(_rule(mode="ml"))
        clickhouse = _ClickHouse(value=10.0)
        clickhouse.latest_score, clickhouse.episode_score = 0.6, 0.3

        assert _kinds(await _cycle_of(rule.rule_id, clickhouse)) == []

    @pytest.mark.asyncio
    async def test_without_any_score_it_judges_on_the_threshold(self, postgres):
        rule = await alert_store.create_rule(_rule(mode="ml"))

        assert _kinds(await _cycle_of(rule.rule_id, _ClickHouse(value=95.0))) == [KIND_FIRING]


# ── Grouping ──────────────────────────────────────────────────────────────────

def _event(rule_id, server_id: str = _SERVER, state: str = STATE_FIRING) -> AlertEvent:
    return AlertEvent(
        event_id=uuid4(), rule_id=rule_id, server_id=server_id, metric_name="disk_usage_percent", value=96.0,
        threshold=95.0, severity="critical", state=state, triggered_at=_now(),
    )


def _out(rule_id, text_: str, server_id: str = _SERVER, kind: str = KIND_FIRING) -> Outgoing:
    return Outgoing(Line(kind, text_, _event(rule_id, server_id)))


async def _channel(rule_id=None, server_id: str | None = _SERVER, scope: str = SCOPE_SERVER) -> AlertChannel:
    return await alert_store.create_channel(AlertChannel(
        channel_id=uuid4(), rule_id=rule_id, server_id=server_id, channel_type="webhook",
        config={"url": "https://hooks.example.test/x"}, created_at=_now(), scope=scope,
    ))


class TestGrouping:
    @pytest.mark.asyncio
    async def test_a_burst_on_one_server_is_one_message_per_channel(self, postgres):
        await server_store.register_servers([_SERVER, "db-1"])
        everything = await _channel(scope=SCOPE_GLOBAL, server_id=None)
        disk = (await alert_store.create_rule(_rule(metric="disk_usage_percent"))).rule_id
        memory, cpu = uuid4(), uuid4()
        only_disk = await _channel(rule_id=disk)
        outgoing = [_out(disk, "disk"), _out(memory, "memory"), _out(cpu, "cpu"), _out(uuid4(), "db", server_id="db-1")]

        messages = await alert_outbox.compose(outgoing)

        by = {(m.channel.channel_id, m.notification.server_id): m.notification for m in messages}
        grouped = by[(everything.channel_id, _SERVER)]
        assert grouped.kind == KIND_GROUPED
        assert [line.text for line in grouped.lines] == ["disk", "memory", "cpu"]
        assert grouped.text.splitlines()[1:] == ["disk", "memory", "cpu"]
        assert by[(only_disk.channel_id, _SERVER)].text == "disk"
        assert by[(everything.channel_id, "db-1")].text == "db"
        assert len(messages) == 3

    @pytest.mark.asyncio
    async def test_the_history_keeps_one_row_per_alert_of_a_grouped_message(self, postgres, monkeypatch):
        await server_store.register_servers([_SERVER])
        await _channel(scope=SCOPE_GLOBAL, server_id=None)
        clickhouse = _ClickHouse()

        async def ok(_config, _notification, _client):
            return None

        monkeypatch.setitem(notification_dispatcher.SENDERS, "webhook", ok)
        await alert_outbox.send([_out(uuid4(), "a"), _out(uuid4(), "b", kind=KIND_NO_DATA)], clickhouse)

        assert [(r.kind, r.ok) for r in clickhouse.records] == [(KIND_FIRING, True), (KIND_NO_DATA, True)]


# ── Retries ───────────────────────────────────────────────────────────────────

async def _firing_alert() -> tuple[AlertRule, AlertEvent]:
    """A rule firing on the server, and the event the channels were told about."""
    rule = await alert_store.create_rule(_rule())
    await _cycle_of(rule.rule_id, _ClickHouse(value=95.0))
    state = (await _item(rule.rule_id)).state
    event = AlertEvent(
        event_id=state.last_event_id, rule_id=rule.rule_id, server_id=_SERVER, metric_name=rule.metric_name,
        value=95.0, threshold=rule.threshold, severity=rule.severity, state=STATE_FIRING, triggered_at=_now(),
    )
    return rule, event


async def _retries() -> list[NotificationRetryRow]:
    async with db.session() as s:
        return list(await s.scalars(select(NotificationRetryRow)))


def _results(monkeypatch, outcomes: list[bool]) -> list[Notification]:
    """Each delivery answers the next outcome; returns what was sent."""
    sent: list[Notification] = []

    async def dispatch_one(channel, notification, _writer, _client=None):
        sent.append(notification)
        ok = outcomes.pop(0)
        return DeliveryResult(channel, ok=ok, error="" if ok else "timeout")

    monkeypatch.setattr(notification_retries, "dispatch_one", dispatch_one)
    monkeypatch.setattr(alert_outbox, "dispatch_one", dispatch_one)
    return sent


class TestRetries:
    @pytest.mark.asyncio
    async def test_a_failed_delivery_is_retried_later_and_marked_late(self, postgres, monkeypatch):
        _rule_, event = await _firing_alert()
        channel = await _channel()
        sent = _results(monkeypatch, [False, True])
        first = _now()

        await alert_outbox.send([Outgoing(Line(KIND_FIRING, "disk", event))], _ClickHouse())
        [row] = await _retries()
        assert (row.attempts, row.last_error, row.channel_id) == (1, "timeout", channel.channel_id)
        assert row.next_attempt_at - first >= notification_retries.RETRY_DELAYS[0] - timedelta(seconds=5)

        assert await notification_retries.run_due(_ClickHouse(), now=first + timedelta(minutes=2)) == 1
        assert await _retries() == []
        assert sent[-1].text.endswith("disk") and sent[-1].text != "disk"  # says how late

    @pytest.mark.asyncio
    async def test_the_wait_grows_and_the_retries_stop_at_the_limit(self, postgres, monkeypatch):
        _rule_, event = await _firing_alert()
        await _channel()
        _results(monkeypatch, [False] * notification_retries.MAX_ATTEMPTS)
        await alert_outbox.send([Outgoing(Line(KIND_FIRING, "disk", event))], _ClickHouse())

        waits = []
        clock = _now()
        while rows := await _retries():
            [row] = rows
            waits.append(row.next_attempt_at)
            clock = row.next_attempt_at
            await notification_retries.run_due(_ClickHouse(), now=clock)

        gaps = [round((b - a).total_seconds() / 60) for a, b in zip(waits, waits[1:])]
        assert gaps == [2, 4, 8, 16, 32]
        assert len(waits) == notification_retries.MAX_ATTEMPTS - 1

    @pytest.mark.asyncio
    async def test_a_retry_whose_alert_changed_since_is_dropped(self, postgres, monkeypatch):
        rule, event = await _firing_alert()
        await _channel()
        sent = _results(monkeypatch, [False])
        await alert_outbox.send([Outgoing(Line(KIND_FIRING, "disk", event))], _ClickHouse())
        await _cycle_of(rule.rule_id, _ClickHouse(value=50.0))  # resolved meanwhile: a new event

        await notification_retries.run_due(_ClickHouse(), now=_now() + timedelta(minutes=5))

        assert await _retries() == []
        assert len(sent) == 1  # the stale "firing" was not sent again

    @pytest.mark.asyncio
    async def test_a_test_send_is_not_retried(self, postgres, monkeypatch):
        channel = await _channel()
        await notification_retries.schedule(channel.channel_id, Notification(kind="test", server_id=_SERVER, text="t"), "x")

        assert await _retries() == []


# ── Texts ─────────────────────────────────────────────────────────────────────

class TestTexts:
    def test_lines_of_the_cycle(self):
        event = _event(uuid4())
        assert no_data_text(event) == "⚪ Sem dados em web-1: Disco parou de chegar"
        assert reminder_text(event, 25 * 60) == "🔁 Crítico em web-1: Disco em 96% (limite 95%), há 25 min"
        assert alert_text(event) + late_suffix(12 * 60) == (
            "🔴 Crítico em web-1: Disco em 96% (limite 95%) · há 12 min, durante um silêncio ou manutenção"
        )
        assert acknowledged_text(event, "ana", "Aplicações") == "👀 ana reconheceu: Crítico em Aplicações (web-1): Disco"
        assert delayed_text("x", 7 * 60) == "⏱ Atrasada 7 min · x"

    def test_several_lines_name_the_server_once_above_them(self):
        assert grouped_text("web-1", ["a"]) == "a"
        assert grouped_text("web-1", ["a", "b"], "Aplicações") == "📣 2 avisos de Aplicações (web-1):\na\nb"


# ── Routes ────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(postgres, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.ch_writer = _ClickHouse()
    app.state.ch_reader = _ClickHouse(value=96.0)
    app.state.vuln_redis = _Redis()
    act_as(app, role="operator", user_id=1, username="ana")
    return TestClient(app)


class TestRoutes:
    @pytest.mark.asyncio
    async def test_acknowledge_lists_who_tells_the_channels_and_audits(self, client, monkeypatch):
        await _user()
        await server_store.register_servers([_SERVER])
        rule = await alert_store.create_rule(_rule())
        await _cycle_of(rule.rule_id, _ClickHouse(value=95.0))
        told: list = []
        monkeypatch.setattr(alert_outbox, "send_soon", lambda outgoing, *_a: told.extend(outgoing))

        [open_] = client.get("/alerts/open").json()
        assert (open_["state"], open_["acknowledged_by"], open_["value"]) == (STATE_FIRING, None, 96.0)
        acked = client.post(f"/alerts/{_SERVER}/rules/{rule.rule_id}/acknowledge")

        assert acked.status_code == 200, acked.text
        assert acked.json()["acknowledged_by"] == "ana"
        assert client.get("/alerts/open").json()[0]["acknowledged_by"] == "ana"
        assert [o.line.kind for o in told] == [KIND_ACKNOWLEDGED]
        assert client.post(f"/alerts/{_SERVER}/rules/{rule.rule_id}/acknowledge").status_code == 409
        async with db.session() as s:
            actions = list(await s.scalars(select(AuditLogRow.action)))
        assert actions.count("alert_state.acknowledge") == 1

    @pytest.mark.asyncio
    async def test_acknowledging_during_maintenance_tells_nobody(self, client, monkeypatch):
        from app import maintenance

        await _user()
        await server_store.register_servers([_SERVER])
        rule = await alert_store.create_rule(_rule())
        await _cycle_of(rule.rule_id, _ClickHouse(value=95.0))
        await maintenance.create_window(_SERVER, "upgrade", 1, once=(_now() - timedelta(minutes=1), _now() + timedelta(hours=1)))
        told: list = []
        monkeypatch.setattr(alert_outbox, "send_soon", lambda outgoing, *_a: told.extend(outgoing))

        body = client.post(f"/alerts/{_SERVER}/rules/{rule.rule_id}/acknowledge").json()

        assert (body["quiet"], told) == ("maintenance", [])

    @pytest.mark.asyncio
    async def test_a_calm_alert_cannot_be_acknowledged(self, client):
        await _user()
        rule = await alert_store.create_rule(_rule())

        assert client.post(f"/alerts/{_SERVER}/rules/{rule.rule_id}/acknowledge").status_code == 404

    @pytest.mark.asyncio
    async def test_an_overridden_rule_no_longer_shows_as_open(self, client):
        await server_store.register_servers([_SERVER])
        inherited = await alert_store.create_rule(_rule(scope=SCOPE_GLOBAL))
        await _cycle_of(inherited.rule_id, _ClickHouse(value=95.0))
        own = _rule()
        own.threshold = 99.0
        await alert_store.create_rule(own)

        assert client.get("/alerts/open").json() == []

    @pytest.mark.asyncio
    async def test_waiting_retries_are_listed_for_the_server(self, client, monkeypatch):
        _rule_, event = await _firing_alert()
        await _channel()
        _results(monkeypatch, [False])
        await alert_outbox.send([Outgoing(Line(KIND_FIRING, "disk", event))], _ClickHouse())

        [retry] = client.get(f"/alerts/{_SERVER}/retries").json()

        assert (retry["attempts"], retry["max_attempts"], retry["kinds"]) == (1, 7, [KIND_FIRING])


# ── What the screen needs from the scoped routes ──────────────────────────────

@pytest.fixture
def scoped_client(postgres) -> TestClient:
    from app.scoped_alerts import router as scoped_router

    app = FastAPI()
    app.include_router(scoped_router)
    act_as(app, role="operator", user_id=1, username="ana")
    return TestClient(app)


class TestScreenRoutes:
    @pytest.mark.asyncio
    async def test_without_a_scope_every_rule_of_every_place_is_listed(self, scoped_client):
        await alert_store.create_rule(_rule(scope=SCOPE_GLOBAL))
        await alert_store.create_rule(_rule())

        listed = scoped_client.get("/alerts/rules").json()

        assert sorted(r["scope"] for r in listed) == ["global", "server"]
        assert scoped_client.get("/alerts/rules", params={"server_id": _SERVER}).status_code == 422

    @pytest.mark.asyncio
    async def test_a_channel_moves_to_every_server_keeping_its_config_and_audited(self, scoped_client):
        await _user()
        channel = await _channel()

        moved = scoped_client.post(f"/alerts/channels/{channel.channel_id}/move", json={"scope": "global"})

        assert moved.status_code == 200, moved.text
        assert (moved.json()["scope"], moved.json()["server_id"]) == ("global", None)
        stored = await alert_store.get_channel_by_id(channel.channel_id)
        assert stored.config == {"url": "https://hooks.example.test/x"}
        async with db.session() as s:
            actions = list(await s.scalars(select(AuditLogRow.action)))
        assert "alert_channels.move" in actions
        assert scoped_client.post(f"/alerts/channels/{uuid4()}/move", json={"scope": "global"}).status_code == 404


class TestAuditTargets:
    @pytest.mark.asyncio
    async def test_servers_groups_quiet_periods_and_acknowledgements_are_described(self, postgres):
        from app import audit, maintenance, silences
        from app.rule_scope import Place

        author = await _user()
        await server_store.register_servers([_SERVER])
        group = await server_store.create_group("Web")
        rule = await alert_store.create_rule(_rule())
        silence = await silences.create_silence(
            Place(SCOPE_SERVER, server_id=_SERVER), None, _now(), _now() + timedelta(hours=1), "deploy", author,
        )
        window = await maintenance.create_window(
            _SERVER, "upgrade", author, once=(_now() + timedelta(days=1), _now() + timedelta(days=1, hours=1)),
        )
        entries = [
            {"target_table": "servers", "target_id": _SERVER},
            {"target_table": "server_groups", "target_id": str(group.group_id)},
            {"target_table": "alert_silences", "target_id": str(silence.silence_id)},
            {"target_table": "maintenance_windows", "target_id": str(window.window_id)},
            {"target_table": "alert_state", "target_id": f"{rule.rule_id}:{_SERVER}"},
        ]

        found = await audit.describe_targets(entries)

        assert {kind["kind"] for kind in found.values()} == {"server", "group", "silence", "maintenance", "alert"}
        assert found[("alert_state", f"{rule.rule_id}:{_SERVER}")]["metric_name"] == "cpu_usage_percent"
        assert found[("maintenance_windows", str(window.window_id))]["reason"] == "upgrade"


class TestOverriddenState:
    @pytest.mark.asyncio
    async def test_an_overridden_rule_no_longer_counts_as_firing_on_the_server(self, postgres):
        await server_store.register_servers([_SERVER])
        inherited = await alert_store.create_rule(_rule(scope=SCOPE_GLOBAL))
        await _cycle_of(inherited.rule_id, _ClickHouse(value=95.0))
        assert list((await alert_store.firing_severities(_SERVER)).values()) == ["critical"]

        own = _rule()
        own.threshold = 99.0
        await alert_store.create_rule(own)

        assert await alert_store.firing_severities(_SERVER) == {}
