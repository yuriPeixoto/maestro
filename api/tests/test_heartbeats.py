"""
Each server's last heartbeat, from Redis, NATS or both: with both, the newest counts per server,
and one source failing leaves the other's answer.
"""
from __future__ import annotations

import json

import pytest

from app import heartbeats
from app.heartbeats import MergedHeartbeats, newest, state_from_message


def _state(last_seen: str, version: str = "0.4.0") -> str:
    return json.dumps({"last_seen": last_seen, "agent_version": version, "watched_logs": [], "inventory": []})


class _Source:
    def __init__(self, states: dict[str, str] | None = None, fail: bool = False) -> None:
        self.states = states or {}
        self.fail = fail

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("down")

    async def all(self):
        self._check()
        return dict(self.states)

    async def get(self, server_id):
        self._check()
        return self.states.get(server_id)

    async def get_many(self, server_ids):
        self._check()
        return [self.states.get(s) for s in server_ids]

    async def ping(self):
        self._check()

    async def close(self):
        return None


_OLD = _state("2026-11-27T12:00:00+00:00", "0.3.1")
_NEW = _state("2026-11-27T12:00:30+00:00", "0.4.0")


def test_newest_prefers_the_latest_heartbeat_and_falls_back_to_an_unreadable_one():
    assert newest([_OLD, _NEW, None]) == _NEW
    assert newest([None, "garbage"]) == "garbage"
    assert newest([None, None]) is None


class TestMerged:
    @pytest.mark.asyncio
    async def test_the_newest_of_each_server_across_sources(self):
        merged = MergedHeartbeats(
            [_Source({"web-1": _OLD, "db-1": _OLD}), _Source({"web-1": _NEW, "gf-1": _NEW})], ["redis", "nats"],
        )

        assert await merged.all() == {"web-1": _NEW, "db-1": _OLD, "gf-1": _NEW}
        assert await merged.get("web-1") == _NEW
        assert await merged.get_many(["db-1", "nobody", "gf-1"]) == [_OLD, None, _NEW]

    @pytest.mark.asyncio
    async def test_one_source_down_leaves_the_other(self):
        merged = MergedHeartbeats([_Source({"web-1": _OLD}), _Source(fail=True)], ["redis", "nats"])

        assert await merged.all() == {"web-1": _OLD}

    @pytest.mark.asyncio
    async def test_every_source_down_raises(self):
        merged = MergedHeartbeats([_Source(fail=True), _Source(fail=True)], ["redis", "nats"])

        with pytest.raises(ConnectionError):
            await merged.all()


def _envelope(subject_server: str, payload_server: str, data_server: str, msg_type: str = "heartbeat") -> bytes:
    return json.dumps({
        "id": "0193a0b8-7c3e-7000-8000-000000000001", "server_id": payload_server, "type": msg_type,
        "sent_at": "2026-11-27T12:00:30Z",
        "data": {"server_id": data_server, "timestamp": "2026-11-27T12:00:30.5Z", "agent_version": "0.4.0",
                 "watched_logs": ["/var/log/a.log"], "inventory": [{"name": "php"}]},
    }).encode()


class TestStateFromMessage:
    def test_a_heartbeat_becomes_the_shared_state_json(self):
        raw = state_from_message("maestro.ingest.web-1.heartbeat", _envelope("web-1", "web-1", "web-1"))

        assert json.loads(raw) == {
            "last_seen": "2026-11-27T12:00:30.500000+00:00", "agent_version": "0.4.0",
            "watched_logs": ["/var/log/a.log"], "inventory": [{"name": "php"}],
        }

    @pytest.mark.parametrize(("payload_server", "data_server", "msg_type"), [
        ("web-2", "web-1", "heartbeat"), ("web-1", "web-2", "heartbeat"), ("web-1", "web-1", "metrics"),
    ])
    def test_a_heartbeat_naming_another_server_or_of_another_type_is_unusable(
        self, payload_server, data_server, msg_type,
    ):
        payload = _envelope("web-1", payload_server, data_server, msg_type)

        assert state_from_message("maestro.ingest.web-1.heartbeat", payload) is None


class TestBuildSource:
    @pytest.mark.parametrize(("transport", "kind"), [
        ("redis", heartbeats.RedisHeartbeats), ("nats", heartbeats.NatsHeartbeats), ("both", MergedHeartbeats),
    ])
    def test_follows_the_transport(self, monkeypatch, transport, kind):
        monkeypatch.setattr(heartbeats.settings, "transport", transport)
        monkeypatch.setattr(heartbeats.settings, "nats_url", "nats://localhost:4222")

        assert isinstance(heartbeats.build_source("maestro-api", "seed.nk", "test", redis=object()), kind)

    def test_reading_nats_without_a_url_fails_at_startup(self, monkeypatch):
        monkeypatch.setattr(heartbeats.settings, "transport", "both")
        monkeypatch.setattr(heartbeats.settings, "nats_url", "")

        with pytest.raises(RuntimeError, match="MAESTRO_NATS_URL"):
            heartbeats.build_source("maestro-api", "seed.nk", "test")
