"""
What the ingest consumers make of each NATS message: the server comes from the subject, a message
that names another server is dropped, and events land in Postgres keeping only the newest.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app import agent_store, nats_ingest
from app.nats_ingest import Unreadable, open_envelope

_SENT = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


def _payload(server: str, msg_type: str, data, sent_at: datetime = _SENT, msg_id: str | None = None) -> bytes:
    return json.dumps({
        "id": msg_id or str(uuid4()), "server_id": server, "type": msg_type,
        "sent_at": sent_at.isoformat().replace("+00:00", "Z"), "data": data,
    }).encode()


def _metric(server: str, name: str = "cpu_usage_percent", value: float = 12.5) -> dict:
    return {"server_id": server, "metric_name": name, "value": value, "timestamp": "2026-11-27T11:59:58.123456789Z"}


@dataclass
class _Msg:
    subject: str
    data: bytes


class _Writer:
    def __init__(self) -> None:
        self.metrics: list = []
        self.logs: list = []

    async def insert_batch(self, rows):
        self.metrics.extend(rows)

    async def insert_log_batch(self, rows):
        self.logs.extend(rows)


class TestEnvelope:
    def test_takes_the_server_from_the_subject(self):
        envelope = open_envelope("maestro.ingest.web-1.metrics", _payload("web-1", "metrics", []))

        assert (envelope.server_id, envelope.type, envelope.sent_at) == ("web-1", "metrics", _SENT)
        assert envelope.msg_id is not None

    def test_refuses_a_payload_that_names_another_server(self):
        with pytest.raises(Unreadable, match="names server 'web-2'"):
            open_envelope("maestro.ingest.web-1.metrics", _payload("web-2", "metrics", []))

    @pytest.mark.parametrize("subject", ["maestro.ingest.web.1.metrics", "maestro.cmd.web-1", "other"])
    def test_refuses_a_subject_that_is_not_an_ingest_subject(self, subject):
        with pytest.raises(Unreadable):
            open_envelope(subject, _payload("web-1", "metrics", []))

    @pytest.mark.parametrize("payload", [b"not json", b"{}", b'{"server_id": "web-1"}', b"[]"])
    def test_refuses_an_unreadable_payload(self, payload):
        with pytest.raises(Unreadable):
            open_envelope("maestro.ingest.web-1.metrics", payload)


class TestHandlers:
    @pytest.mark.asyncio
    async def test_metrics_of_good_messages_are_written_and_bad_ones_dropped(self, postgres):
        writer = _Writer()
        messages = [
            _Msg("maestro.ingest.web-1.metrics", _payload("web-1", "metrics", [_metric("web-1"), {"bad": 1}])),
            _Msg("maestro.ingest.web-1.metrics", _payload("web-2", "metrics", [_metric("web-2")])),
            _Msg("maestro.ingest.web-1.metrics", _payload("web-1", "logs", {})),
            _Msg("maestro.ingest.web-1.metrics", b"garbage"),
            _Msg("maestro.ingest.web-1.metrics", _payload("web-1", "metrics", [_metric("web-2")])),
        ]

        await nats_ingest.metrics_handler(writer)(messages)

        assert [(r.server_id, r.metric_name, r.value) for r in writer.metrics] == [("web-1", "cpu_usage_percent", 12.5)]
        assert writer.metrics[0].timestamp == datetime(2026, 11, 27, 11, 59, 58, 123456, tzinfo=timezone.utc)

    @pytest.mark.asyncio
    async def test_a_redelivered_message_is_not_written_again(self, postgres):
        writer = _Writer()
        message = _Msg("maestro.ingest.web-1.metrics", _payload("web-1", "metrics", [_metric("web-1")]))

        await nats_ingest.metrics_handler(writer)([message])
        await nats_ingest.metrics_handler(writer)([message])

        assert len(writer.metrics) == 1

    @pytest.mark.asyncio
    async def test_log_lines_take_the_subject_server_and_their_file(self, postgres):
        writer = _Writer()
        data = {"log_file": "/var/log/app.log", "lines": [
            {"timestamp": "2026-11-27T11:59:00Z", "line": "one"},
            {"timestamp": "bad", "line": "two"},
            {"timestamp": "2026-11-27T11:59:01Z", "line": "three"},
        ]}

        await nats_ingest.logs_handler(writer)([_Msg("maestro.ingest.web-1.logs", _payload("web-1", "logs", data))])

        assert [(r.server_id, r.log_file, r.line) for r in writer.logs] == [
            ("web-1", "/var/log/app.log", "one"), ("web-1", "/var/log/app.log", "three"),
        ]


def _event(server: str, msg_type: str, data, sent_at: datetime = _SENT) -> _Msg:
    return _Msg(f"maestro.ingest.{server}.events", _payload(server, msg_type, data, sent_at))


_REGISTRATION = {"hostname": "web-1.local", "os": "linux", "tags": ["web"], "agent_version": "0.4.0"}


class TestEvents:
    @pytest.mark.asyncio
    async def test_registration_then_goodbye_and_a_late_older_announcement_changes_nothing(self, postgres):
        handle = nats_ingest.events_handler()

        await handle([_event("web-1", "agent_registered", _REGISTRATION)])
        await handle([_event("web-1", "agent_deregistered", _REGISTRATION, _SENT + timedelta(minutes=5))])
        await handle([_event("web-1", "agent_registered", {**_REGISTRATION, "agent_version": "0.3.1"},
                             _SENT + timedelta(minutes=1))])

        agent = await agent_store.get_agent("web-1")
        assert (agent.hostname, agent.os, agent.tags, agent.agent_version) == ("web-1.local", "linux", ["web"], "0.4.0")
        assert agent.registered_at == _SENT
        assert agent.deregistered_at == _SENT + timedelta(minutes=5)
        assert await agent_store.registered_server_ids() == set()

        await handle([_event("web-1", "agent_registered", _REGISTRATION, _SENT + timedelta(minutes=10))])
        assert await agent_store.registered_server_ids() == {"web-1"}

    @pytest.mark.asyncio
    async def test_an_event_for_another_server_is_dropped(self, postgres):
        message = _Msg("maestro.ingest.web-1.events", _payload("web-2", "agent_registered", _REGISTRATION))

        await nats_ingest.events_handler()([message])

        assert await agent_store.list_agents() == []

    @pytest.mark.asyncio
    async def test_packages_and_db_connections_keep_the_newest(self, postgres):
        handle = nats_ingest.events_handler()
        newer = {"ecosystem": "Debian:13", "packages": [{"name": "openssl", "version": "3.5"}]}
        older = {"ecosystem": "Debian:12", "packages": []}
        conns = {"db_type": "postgres", "connections": [{"user": "app", "host": "x", "elapsed_sec": 3}]}

        await handle([
            _event("web-1", "packages", newer, _SENT + timedelta(minutes=1)),
            _event("web-1", "packages", older),
            _event("web-1", "db_connections", conns),
            _event("web-1", "db_connections", {"connections": []}),
            _event("web-1", "something_new", {}),
        ])

        assert await agent_store.packages_of("web-1") == newer
        [snapshot] = await agent_store.db_snapshots_of("web-1")
        assert (snapshot.db_type, snapshot.connections, snapshot.sent_at) == ("postgres", conns["connections"], _SENT)
