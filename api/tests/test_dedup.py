"""
A message the agent sent through Redis and through NATS is written once, and a failed write leaves
nothing claimed, so the redelivered message is written later.
"""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app import db, dedup


class _Insert:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.rows: list = []

    async def __call__(self, rows: list) -> None:
        if self.fail:
            raise RuntimeError("clickhouse down")
        self.rows.extend(rows)


async def _claimed() -> dict[UUID, str]:
    async with db.session() as session:
        rows = await session.execute(text("SELECT msg_id, source FROM ingested_messages"))
        return {msg_id: source for msg_id, source in rows}


class TestWriteOnce:
    @pytest.mark.asyncio
    async def test_nats_writes_a_message_once(self, postgres):
        msg = uuid4()
        insert = _Insert()

        assert await dedup.write_once([(msg, ["a", "b"])], "nats", "metrics", insert) == 2
        assert await dedup.write_once([(msg, ["a", "b"])], "nats", "metrics", insert) == 0

        assert insert.rows == ["a", "b"]
        assert await _claimed() == {msg: "nats"}

    @pytest.mark.asyncio
    async def test_what_nats_wrote_is_dropped_on_the_redis_path_and_back(self, postgres):
        from_nats, from_redis = uuid4(), uuid4()
        insert = _Insert()
        await dedup.write_once([(from_nats, ["n1", "n2"])], "nats", "metrics", insert)
        await dedup.write_once([(from_redis, ["r1"])], "redis", "metrics", insert)

        await dedup.write_once([(from_nats, ["n1"]), (from_nats, ["n2"])], "redis", "metrics", insert)
        await dedup.write_once([(from_redis, ["r1", "r2"])], "nats", "metrics", insert)

        assert insert.rows == ["n1", "n2", "r1"]

    @pytest.mark.asyncio
    async def test_the_rest_of_a_message_redis_split_across_reads_is_still_written(self, postgres):
        msg = uuid4()
        insert = _Insert()

        await dedup.write_once([(msg, ["m1"]), (msg, ["m2"])], "redis", "metrics", insert)
        await dedup.write_once([(msg, ["m3"])], "redis", "metrics", insert)

        assert insert.rows == ["m1", "m2", "m3"]

    @pytest.mark.asyncio
    async def test_a_failed_write_claims_nothing(self, postgres):
        msg = uuid4()

        with pytest.raises(RuntimeError):
            await dedup.write_once([(msg, ["a"])], "nats", "logs", _Insert(fail=True))
        assert await _claimed() == {}

        retry = _Insert()
        assert await dedup.write_once([(msg, ["a"])], "nats", "logs", retry) == 1
        assert retry.rows == ["a"]

    @pytest.mark.asyncio
    async def test_messages_without_an_id_are_always_written_without_postgres(self, monkeypatch):
        def no_database(*_args, **_kwargs):
            raise AssertionError("Postgres was used")

        monkeypatch.setattr(db, "session", no_database)
        insert = _Insert()

        assert await dedup.write_once([(None, ["a"]), (None, ["b"])], "redis", "metrics", insert) == 2
        assert insert.rows == ["a", "b"]

    @pytest.mark.asyncio
    async def test_the_second_path_waits_for_the_first_and_then_drops_the_message(self, postgres):
        msg = uuid4()
        writing, release = asyncio.Event(), asyncio.Event()
        rows: list = []

        async def slow_insert(batch: list) -> None:
            writing.set()
            await release.wait()
            rows.extend(batch)

        first = asyncio.create_task(dedup.write_once([(msg, ["from-redis"])], "redis", "metrics", slow_insert))
        await writing.wait()
        second = asyncio.create_task(dedup.write_once([(msg, ["from-nats"])], "nats", "metrics", _Insert()))
        await asyncio.sleep(0.3)
        assert not second.done()  # waiting on the first path's uncommitted claim

        release.set()
        assert await first == 1
        assert await second == 0
        assert rows == ["from-redis"]

    @pytest.mark.asyncio
    async def test_counts_rows_received_and_written_per_path(self, postgres):
        dedup.take_counts()
        msg = uuid4()
        await dedup.write_once([(msg, ["a", "b"]), (None, ["c"])], "nats", "metrics", _Insert())
        await dedup.write_once([(msg, ["a"]), (msg, ["b"])], "redis", "metrics", _Insert())

        counts = dedup.take_counts()

        nats, redis = counts[("nats", "metrics")], counts[("redis", "metrics")]
        assert (nats.received, nats.written) == (3, 3)
        assert (redis.received, redis.written) == (2, 0)
        assert dedup.take_counts() == {}


class TestPurge:
    @pytest.mark.asyncio
    async def test_forgets_only_ids_older_than_the_retention(self, postgres):
        old, recent = uuid4(), uuid4()
        await dedup.write_once([(old, ["a"]), (recent, ["b"])], "nats", "metrics", _Insert())
        async with db.session() as session:
            await session.execute(
                text("UPDATE ingested_messages SET received_at = now() - interval '8 days' WHERE msg_id = :id"),
                {"id": old},
            )

        assert await dedup.purge_expired() == 1
        assert list(await _claimed()) == [recent]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0193a0b8-7c3e-7000-8000-000000000001", UUID("0193a0b8-7c3e-7000-8000-000000000001")),
        ("", None),
        (None, None),
        ("not-a-uuid", None),
        (42, None),
    ],
)
def test_parse_id(raw, expected):
    assert dedup.parse_id(raw) == expected
