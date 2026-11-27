"""
A JetStream message is acked only after its batch was written; a failed batch is handed back
with a growing delay and comes back.

The fake subscription keeps what is due and what was acked, so these tests check what would be
lost or replayed, not the NATS protocol.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from nats.errors import TimeoutError as NatsTimeoutError
from nats.js.errors import FetchDisconnectedError

from app.jetstream_reader import consume_jetstream


class _Stop(Exception):
    pass


@dataclass
class _Msg:
    name: str
    sub: "_Subscription"

    async def ack(self) -> None:
        self.sub.acked.append(self.name)

    async def nak(self, delay: float | None = None) -> None:
        self.sub.naked.append((self.name, delay))
        self.sub.due.append(self.name)


@dataclass
class _Subscription:
    due: list[str]
    acked: list[str] = field(default_factory=list)
    naked: list[tuple[str, float | None]] = field(default_factory=list)
    errors: list[Exception] = field(default_factory=list)
    fetches: int = 0

    async def fetch(self, batch: int, timeout: float):
        self.fetches += 1
        if self.errors:
            raise self.errors.pop(0)
        if not self.due:
            raise NatsTimeoutError
        taken, self.due = self.due[:batch], self.due[batch:]
        return [_Msg(name, self) for name in taken]


async def _no_sleep(_seconds: float) -> None:
    return None


def _stop_after(sub: _Subscription, cycles: int):
    beats = []

    def on_cycle() -> None:
        beats.append(sub.fetches)
        if len(beats) >= cycles:
            raise _Stop

    return on_cycle, beats


@pytest.mark.asyncio
async def test_acks_a_batch_only_after_it_was_handled():
    sub = _Subscription(due=["m1", "m2", "m3"])
    handled: list[list[str]] = []

    async def handle(messages):
        assert sub.acked == []  # nothing acked before the handler returned
        handled.append([m.name for m in messages])

    on_cycle, _ = _stop_after(sub, 1)
    with pytest.raises(_Stop):
        await consume_jetstream(sub, "c", handle, batch=10, fetch_timeout=1, on_cycle=on_cycle, sleep=_no_sleep)

    assert handled == [["m1", "m2", "m3"]]
    assert sub.acked == ["m1", "m2", "m3"]


@pytest.mark.asyncio
async def test_a_failed_batch_is_handed_back_with_a_growing_delay_and_written_later():
    sub = _Subscription(due=["m1", "m2"])
    attempts = 0
    pauses: list[float] = []

    async def handle(_messages):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise RuntimeError("clickhouse down")

    async def sleep(seconds: float) -> None:
        pauses.append(seconds)

    on_cycle, beats = _stop_after(sub, 1)
    with pytest.raises(_Stop):
        await consume_jetstream(sub, "c", handle, batch=10, fetch_timeout=1, on_cycle=on_cycle, sleep=sleep)

    assert sub.naked == [("m1", 1.0), ("m2", 1.0), ("m1", 2.0), ("m2", 2.0)]
    assert pauses == [1.0, 2.0]
    assert sub.acked == ["m1", "m2"]
    assert len(beats) == 1  # no beat while failing


@pytest.mark.asyncio
async def test_an_empty_fetch_is_a_healthy_cycle_but_a_disconnect_is_not():
    sub = _Subscription(due=[], errors=[FetchDisconnectedError(), RuntimeError("blip")])

    async def handle(_messages):
        raise AssertionError("nothing to handle")

    on_cycle, beats = _stop_after(sub, 1)
    with pytest.raises(_Stop):
        await consume_jetstream(sub, "c", handle, batch=10, fetch_timeout=1, on_cycle=on_cycle, sleep=_no_sleep)

    assert beats == [3]  # the disconnect and the error were not counted as cycles
