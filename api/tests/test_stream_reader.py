"""
A stream message is acked only after its batch was written.

The fake Redis keeps a stream, the group's pending list (PEL) and the acks, so
these tests check what would be lost or replayed, not the Redis wire protocol.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app import clickhouse
from app.clickhouse import ClickHouseWriter, InsertFailed
from app.consumer import metric_batch_handler
from app.stream_reader import StreamSpec, consume_stream

_SPEC = StreamSpec(stream="s", group="g", consumer="c", count=10, block_ms=1)


class _Stop(Exception):
    pass


@dataclass
class _FakeStreamRedis:
    new: list[tuple[str, dict]]
    pending: dict[str, dict] = field(default_factory=dict)
    acked: list[str] = field(default_factory=list)
    reads: list[str] = field(default_factory=list)

    async def xgroup_create(self, **_kwargs) -> None:
        return None

    async def xreadgroup(self, groupname, consumername, streams, count, block):
        start_id = next(iter(streams.values()))
        self.reads.append(start_id)
        if start_id == "0":
            batch = list(self.pending.items())[:count]
        else:
            batch, self.new = self.new[:count], self.new[count:]
            self.pending.update(batch)
        return [("s", batch)] if batch else []

    async def xack(self, _stream, _group, *ids) -> None:
        for msg_id in ids:
            self.pending.pop(msg_id, None)
            self.acked.append(msg_id)


async def _no_sleep(_seconds: float) -> None:
    return None


def _stop_when_idle(redis: _FakeStreamRedis):
    def on_cycle() -> None:
        if not redis.new and not redis.pending:
            raise _Stop

    return on_cycle


async def _run(redis: _FakeStreamRedis, handle) -> None:
    with pytest.raises(_Stop):
        await consume_stream(redis, _SPEC, handle, _stop_when_idle(redis), sleep=_no_sleep)


class TestAckAfterWrite:
    @pytest.mark.asyncio
    async def test_failed_batch_stays_pending_and_is_written_on_retry(self):
        redis = _FakeStreamRedis(new=[("1-0", {"data": "a"}), ("2-0", {"data": "b"})])
        attempts: list[list[str]] = []

        async def handle(messages):
            attempts.append([msg_id for msg_id, _ in messages])
            if len(attempts) == 1:
                raise InsertFailed("metrics", len(messages))

        await _run(redis, handle)

        assert attempts == [["1-0", "2-0"], ["1-0", "2-0"]]
        assert redis.acked == ["1-0", "2-0"]
        assert redis.pending == {}

    @pytest.mark.asyncio
    async def test_failed_batch_is_not_acked(self):
        redis = _FakeStreamRedis(new=[("1-0", {"data": "a"})])
        calls = 0

        async def handle(_messages):
            nonlocal calls
            calls += 1
            if calls <= 3:
                raise InsertFailed("metrics", 1)
            assert redis.acked == []

        await _run(redis, handle)

        assert calls == 4

    @pytest.mark.asyncio
    async def test_pending_messages_from_before_a_restart_come_first(self):
        redis = _FakeStreamRedis(new=[("3-0", {"data": "new"})], pending={"1-0": {"data": "old"}})
        seen: list[str] = []

        async def handle(messages):
            seen.extend(msg_id for msg_id, _ in messages)

        await _run(redis, handle)

        assert seen == ["1-0", "3-0"]
        assert redis.reads[0] == "0"

    @pytest.mark.asyncio
    async def test_pending_entry_trimmed_from_the_stream_is_acked_without_handling(self):
        redis = _FakeStreamRedis(new=[], pending={"1-0": {}})
        seen: list[str] = []

        async def handle(messages):
            seen.extend(msg_id for msg_id, _ in messages)

        await _run(redis, handle)

        assert seen == []
        assert redis.acked == ["1-0"]


class _FakeWriter:
    def __init__(self) -> None:
        self.rows: list = []

    async def insert_batch(self, rows) -> None:
        self.rows.extend(rows)


class TestMetricHandler:
    @pytest.mark.asyncio
    async def test_unparseable_message_is_skipped_not_retried(self):
        writer = _FakeWriter()
        good = '{"server_id": "s1", "metric_name": "cpu_usage_percent", "value": 5, "timestamp": "2026-11-03T12:00:00Z"}'

        await metric_batch_handler(writer)([("1-0", {"data": "not json"}), ("2-0", {"data": good})])

        assert [r.metric_name for r in writer.rows] == ["cpu_usage_percent"]


@dataclass
class _FailingClient:
    calls: int = 0

    async def insert(self, *_args, **_kwargs) -> None:
        self.calls += 1
        raise ConnectionError("clickhouse down")


class TestWriterRetry:
    @pytest.mark.asyncio
    async def test_raises_instead_of_dropping_rows(self, monkeypatch):
        monkeypatch.setattr(clickhouse.settings, "consumer_retry_base_delay", 0.0)
        client = _FailingClient()
        writer = ClickHouseWriter(client)

        with pytest.raises(InsertFailed):
            await writer.insert_log_batch([clickhouse.LogRow("s1", "/var/log/x", None, "line")])

        assert client.calls == clickhouse.settings.consumer_retry_max
