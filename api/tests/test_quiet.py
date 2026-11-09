"""
Silences and maintenance windows: a deadline, a reason and an author; windows that the
database keeps from overlapping on one server, weekly ones included; and the evaluator,
which still records an alert it does not send.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import alert_evaluator, alert_store, db, maintenance, server_store, silences
from app.alert_store import STATE_FIRING, AlertRule
from app.maintenance import Weekly, weekly_occurrences
from app.quiet import REASON_MAINTENANCE, REASON_SILENCE, QuietNow, quiet_now
from app.quiet_routes import router
from app.rule_scope import SCOPE_GLOBAL, SCOPE_GROUP, SCOPE_SERVER, Place
from tests.conftest import act_as

_UTC = timezone.utc
_UTC_MINUS_4 = "America/Manaus"  # UTC-4, no daylight saving time
_WITH_DST = "America/New_York"  # a zone with daylight saving time, to check the wall-clock start


def _now() -> datetime:
    return datetime.now(_UTC)


async def _user(user_id: int = 1, username: str = "ana") -> int:
    async with db.session() as s:
        await s.execute(text(
            "INSERT INTO users (id, username, email, password_hash) OVERRIDING SYSTEM VALUE"
            " VALUES (:id, :name, :email, 'x')"
        ), {"id": user_id, "name": username, "email": f"{username}@example.com"})
    return user_id


def _rule(scope: str = SCOPE_GLOBAL, server_id: str | None = None) -> AlertRule:
    return AlertRule(
        rule_id=uuid4(), server_id=server_id, metric_name="cpu_usage_percent", operator=">=", threshold=90.0,
        severity="critical", cooldown_minutes=5, created_at=_now(), scope=scope,
    )


class TestWeeklyOccurrences:
    """Pure: no database."""

    def test_the_chosen_weekdays_at_the_local_time(self):
        weekly = Weekly(weekdays=(1, 3), local_start=time(2, 0), duration=timedelta(hours=1), time_zone=_UTC_MINUS_4)
        monday = datetime(2026, 11, 9, 0, 0, tzinfo=_UTC)

        found = weekly_occurrences(weekly, monday, monday + timedelta(days=7))

        # 02:00 at UTC-4 is 06:00 UTC, on Monday 9 and Wednesday 11.
        assert found == [
            (datetime(2026, 11, 9, 6, 0, tzinfo=_UTC), datetime(2026, 11, 9, 7, 0, tzinfo=_UTC)),
            (datetime(2026, 11, 11, 6, 0, tzinfo=_UTC), datetime(2026, 11, 11, 7, 0, tzinfo=_UTC)),
        ]

    def test_one_that_began_yesterday_and_still_runs_is_included(self):
        weekly = Weekly(weekdays=(7,), local_start=time(23, 0), duration=timedelta(hours=3), time_zone="UTC")
        monday_1am = datetime(2026, 11, 9, 1, 0, tzinfo=_UTC)

        [(begin, finish)] = weekly_occurrences(weekly, monday_1am, monday_1am + timedelta(hours=1))

        assert (begin, finish) == (datetime(2026, 11, 8, 23, 0, tzinfo=_UTC), datetime(2026, 11, 9, 2, 0, tzinfo=_UTC))

    def test_keeps_the_wall_clock_start_across_daylight_saving(self):
        weekly = Weekly(weekdays=(7,), local_start=time(3, 0), duration=timedelta(hours=1), time_zone=_WITH_DST)
        start = datetime(2026, 10, 25, tzinfo=_UTC)

        begins = [b for b, _f in weekly_occurrences(weekly, start, start + timedelta(days=14))]

        # 03:00 in New York: EDT (UTC-4) on 25/10, EST (UTC-5) after 01/11.
        assert [b.hour for b in begins] == [7, 8]

    def test_stops_after_repeat_until(self):
        weekly = Weekly(
            weekdays=tuple(range(1, 8)), local_start=time(2, 0), duration=timedelta(hours=1), time_zone="UTC",
            repeat_until=date(2026, 11, 10),
        )
        start = datetime(2026, 11, 9, tzinfo=_UTC)

        assert len(weekly_occurrences(weekly, start, start + timedelta(days=7))) == 2

    @pytest.mark.parametrize("kwargs", [
        {"weekdays": ()}, {"weekdays": (0,)}, {"weekdays": (8,)}, {"duration": timedelta(0)},
        {"duration": timedelta(hours=25)}, {"time_zone": "Mars/Olympus"},
    ])
    def test_refuses_what_cannot_happen(self, kwargs):
        values = {"weekdays": (1,), "local_start": time(2, 0), "duration": timedelta(hours=1), "time_zone": "UTC"}
        with pytest.raises(ValueError):
            Weekly(**{**values, **kwargs})


class TestQuietNow:
    def test_maintenance_wins_over_a_silence(self):
        rule_id = uuid4()
        silence = silences.Silence(
            silence_id=uuid4(), place=Place(SCOPE_GLOBAL), rule_id=None, starts_at=_now(), ends_at=_now(),
            reason="x", created_by=1, created_by_name="ana", created_at=_now(),
        )
        quiet = QuietNow([silence], {"db-1"})

        assert quiet.reason("db-1", None, rule_id) == REASON_MAINTENANCE
        assert quiet.reason("web-1", None, rule_id) == REASON_SILENCE

    def test_a_silence_covers_its_place_and_rule_only(self):
        rule_id, other_rule = uuid4(), uuid4()

        def silence(place: Place, rule=None) -> silences.Silence:
            return silences.Silence(
                silence_id=uuid4(), place=place, rule_id=rule, starts_at=_now(), ends_at=_now(), reason="x",
                created_by=1, created_by_name="ana", created_at=_now(),
            )

        group = QuietNow([silence(Place(SCOPE_GROUP, group_id=3))])
        one_rule = QuietNow([silence(Place(SCOPE_SERVER, server_id="web-1"), rule_id)])

        assert group.reason("db-1", 3, rule_id) == REASON_SILENCE
        assert group.reason("db-1", 4, rule_id) is None
        assert one_rule.reason("web-1", None, rule_id) == REASON_SILENCE
        assert one_rule.reason("web-1", None, other_rule) is None
        assert one_rule.reason("web-2", None, rule_id) is None


class TestSilencesInPostgres:
    @pytest.mark.asyncio
    async def test_in_force_until_its_deadline_and_ended_early_by_someone(self, postgres):
        author = await _user()
        silence = await silences.create_silence(
            Place(SCOPE_SERVER, server_id="web-1"), None, _now() - timedelta(minutes=1),
            _now() + timedelta(hours=1), "  deploy of the new release ", author,
        )
        assert (silence.reason, silence.created_by_name) == ("deploy of the new release", "ana")
        assert [s.silence_id for s in await silences.active_silences()] == [silence.silence_id]

        assert await silences.end_silence(silence.silence_id, author)

        assert await silences.active_silences() == []
        assert await silences.list_silences() == []
        assert not await silences.end_silence(silence.silence_id, author)  # already over

    @pytest.mark.asyncio
    async def test_one_still_to_come_is_listed_and_can_be_ended_before_it_starts(self, postgres):
        author = await _user()
        later = await silences.create_silence(
            Place(SCOPE_GLOBAL), None, _now() + timedelta(hours=1), _now() + timedelta(hours=2), "night job", author,
        )

        assert await silences.active_silences() == []
        assert [s.silence_id for s in await silences.list_silences()] == [later.silence_id]
        assert await silences.end_silence(later.silence_id, author)
        assert await silences.list_silences() == []

    @pytest.mark.asyncio
    async def test_the_database_wants_a_deadline_and_a_reason(self, postgres):
        await _user()
        for during, reason, constraint in [
            ("tstzrange(now(), NULL)", "x", "alert_silences_during_check"),
            ("tstzrange(now(), now() + interval '1 hour')", "  ", "alert_silences_reason_check"),
        ]:
            with pytest.raises(Exception, match=constraint):
                async with db.session() as s:
                    await s.execute(text(
                        "INSERT INTO alert_silences (silence_id, scope, during, reason, created_by)"
                        f" VALUES (gen_random_uuid(), 'global', {during}, :reason, 1)"
                    ), {"reason": reason})

    @pytest.mark.asyncio
    async def test_is_audited(self, postgres):
        author = await _user()
        silence = await silences.create_silence(
            Place(SCOPE_GLOBAL), None, _now(), _now() + timedelta(hours=1), "x", author,
        )
        await silences.end_silence(silence.silence_id, author)

        async with db.session() as s:
            actions = list(await s.scalars(text(
                "SELECT action FROM audit_log WHERE target_table = 'alert_silences' ORDER BY id"
            )))
        assert actions == ["alert_silences.insert", "alert_silences.end"]


class TestMaintenanceInPostgres:
    @pytest.mark.asyncio
    async def test_a_window_now_puts_the_server_in_maintenance(self, postgres):
        author = await _user()
        await server_store.register_servers(["db-1", "db-2"])

        window = await maintenance.create_window(
            "db-1", "disk swap", author, once=(_now() - timedelta(minutes=5), _now() + timedelta(hours=1)),
        )

        assert window.active_now
        assert await maintenance.servers_in_maintenance() == {"db-1"}

    @pytest.mark.asyncio
    async def test_the_database_refuses_overlapping_windows_on_one_server(self, postgres):
        author = await _user()
        await server_store.register_servers(["db-1", "db-2"])
        start = _now() + timedelta(days=1)
        await maintenance.create_window("db-1", "first", author, once=(start, start + timedelta(hours=2)))

        with pytest.raises(maintenance.Overlap):
            await maintenance.create_window(
                "db-1", "second", author, once=(start + timedelta(hours=1), start + timedelta(hours=3)),
            )
        # Back to back is fine ('[)' ranges), and another server is not affected.
        await maintenance.create_window(
            "db-1", "right after", author, once=(start + timedelta(hours=2), start + timedelta(hours=3)),
        )
        await maintenance.create_window("db-2", "same time", author, once=(start, start + timedelta(hours=2)))

    @pytest.mark.asyncio
    async def test_a_weekly_window_that_hits_another_is_refused_whole(self, postgres):
        author = await _user()
        await server_store.register_servers(["db-1"])
        weekly = Weekly(weekdays=tuple(range(1, 8)), local_start=time(3, 0), duration=timedelta(hours=1), time_zone="UTC")
        nine_days = (_now() + timedelta(days=9)).replace(hour=3, minute=30, second=0, microsecond=0)
        await maintenance.create_window("db-1", "one night", author, once=(nine_days, nine_days + timedelta(hours=1)))

        with pytest.raises(maintenance.Overlap):
            await maintenance.create_window("db-1", "every night", author, weekly=weekly)

        async with db.session() as s:
            assert await s.scalar(text("SELECT count(*) FROM maintenance_windows")) == 1

    @pytest.mark.asyncio
    async def test_a_weekly_window_is_written_ahead_and_extended(self, postgres):
        author = await _user()
        await server_store.register_servers(["db-1"])
        weekly = Weekly(weekdays=(1,), local_start=time(3, 0), duration=timedelta(hours=1), time_zone="UTC")
        created_at = datetime(2026, 11, 9, 12, 0, tzinfo=_UTC)

        window = await maintenance.create_window("db-1", "weekly reboot", author, weekly=weekly, now=created_at)
        async with db.session() as s:
            count = await s.scalar(text("SELECT count(*) FROM maintenance_occurrences"))
        assert count == 8  # the next eight Mondays

        assert await maintenance.extend_weekly_windows(created_at + timedelta(weeks=2)) == 2
        assert await maintenance.extend_weekly_windows(created_at + timedelta(weeks=2)) == 0
        assert window.weekly == weekly

    @pytest.mark.asyncio
    async def test_cancelling_ends_one_running_now_and_removes_the_rest(self, postgres):
        author = await _user()
        await server_store.register_servers(["db-1"])
        weekly = Weekly(
            weekdays=tuple(range(1, 8)), local_start=(_now() - timedelta(minutes=10)).time().replace(microsecond=0),
            duration=timedelta(hours=1), time_zone="UTC",
        )
        window = await maintenance.create_window("db-1", "nightly", author, weekly=weekly)
        assert await maintenance.servers_in_maintenance() == {"db-1"}

        assert await maintenance.cancel_window(window.window_id)

        assert await maintenance.servers_in_maintenance() == set()
        assert await maintenance.list_windows() == []
        async with db.session() as s:
            assert await s.scalar(text("SELECT count(*) FROM maintenance_occurrences")) == 1  # the past part stays

    @pytest.mark.asyncio
    async def test_an_unknown_server_is_refused(self, postgres):
        author = await _user()
        with pytest.raises(maintenance.UnknownServer):
            await maintenance.create_window("ghost", "x", author, once=(_now(), _now() + timedelta(hours=1)))


class _ClickHouse:
    def __init__(self, value: float) -> None:
        self.value = value
        self.events: list = []

    async def get_status_metric_value(self, _server_id, _metric):
        return self.value

    async def get_latest_anomaly_score(self, _server_id, _metric):
        return None

    async def insert_alert_event(self, event) -> None:
        self.events.append(event)


class _Redis:
    async def hget(self, _key, _field):
        return None


class TestEvaluatorStaysQuiet:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["silence", "maintenance", "nothing"])
    async def test_records_the_alert_but_sends_it_only_when_nothing_is_quiet(self, postgres, monkeypatch, kind):
        author = await _user()
        await server_store.register_servers(["web-1"])
        rule = await alert_store.create_rule(_rule())
        if kind == "silence":
            await silences.create_silence(
                Place(SCOPE_GLOBAL), rule.rule_id, _now() - timedelta(minutes=1), _now() + timedelta(hours=1),
                "known spike", author,
            )
        elif kind == "maintenance":
            await maintenance.create_window(
                "web-1", "upgrade", author, once=(_now() - timedelta(minutes=1), _now() + timedelta(hours=1)),
            )
        sent: list = []

        async def notify(event, notify_kind, _writer, *_where):
            sent.append(notify_kind)

        monkeypatch.setattr(alert_evaluator, "_notify", notify)
        clickhouse = _ClickHouse(value=95.0)
        [item] = await alert_store.rules_to_evaluate(["web-1"])

        await alert_evaluator._evaluate_rule(
            item, clickhouse, clickhouse, _Redis(), alert_evaluator._Cycle(await quiet_now()),
        )

        assert [e.state for e in clickhouse.events] == [STATE_FIRING]
        assert (await alert_store.firing_severities("web-1")) != {}
        assert sent == ([] if kind != "nothing" else ["firing"])


@pytest.fixture
def client(postgres) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    act_as(app, role="operator", user_id=1)
    return TestClient(app)


class TestRoutes:
    @pytest.mark.asyncio
    async def test_silence_for_a_while_then_end_it(self, client):
        await _user()

        created = client.post(
            "/alerts/silences",
            json={"scope": "server", "server_id": "web-1", "duration_minutes": 30, "reason": "deploy"},
        )

        assert created.status_code == 201, created.text
        body = created.json()
        assert (body["active"], body["created_by"], body["reason"]) == (True, "ana", "deploy")
        assert len(client.get("/alerts/silences").json()) == 1
        assert client.post(f"/alerts/silences/{body['silence_id']}/end").status_code == 204
        assert client.get("/alerts/silences").json() == []

    @pytest.mark.parametrize("body", [
        {"scope": "global", "duration_minutes": 30},                                  # no reason
        {"scope": "global", "reason": "x"},                                           # no deadline
        {"scope": "global", "reason": "x", "duration_minutes": 30, "ends_at": "2030-01-01T00:00:00Z"},
        {"scope": "global", "reason": "x", "duration_minutes": 60 * 24 * 31},         # over 30 days
        {"scope": "global", "reason": "x", "ends_at": "2020-01-01T00:00:00Z"},        # in the past
    ])
    def test_a_silence_needs_a_reason_and_one_deadline_ahead(self, client, body):
        assert client.post("/alerts/silences", json=body).status_code == 422

    @pytest.mark.asyncio
    async def test_weekly_maintenance_and_its_overlap_conflict(self, client):
        await _user()
        await server_store.register_servers(["db-1"])
        weekly = {"weekdays": [6], "local_start": "02:00", "duration_minutes": 120, "time_zone": _UTC_MINUS_4}

        created = client.post("/alerts/maintenance", json={"server_id": "db-1", "reason": "vacuum", "weekly": weekly})
        again = client.post("/alerts/maintenance", json={"server_id": "db-1", "reason": "again", "weekly": weekly})

        assert created.status_code == 201, created.text
        assert created.json()["weekly"]["weekdays"] == [6]
        assert again.status_code == 409
        [listed] = client.get("/alerts/maintenance", params={"server_id": "db-1"}).json()
        assert "T06:00:00" in listed["next_starts_at"]  # 02:00 at UTC-4
        assert client.delete(f"/alerts/maintenance/{listed['window_id']}").status_code == 204
        assert client.get("/alerts/maintenance").json() == []

    def test_maintenance_is_once_or_weekly(self, client):
        assert client.post("/alerts/maintenance", json={"server_id": "db-1", "reason": "x"}).status_code == 422
        assert client.post(
            "/alerts/maintenance", json={"server_id": "db-1", "reason": "x", "starts_at": "2030-01-01T00:00:00Z"},
        ).status_code == 422
