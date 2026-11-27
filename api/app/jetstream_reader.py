"""Read a JetStream durable pull consumer without losing messages.

The NATS counterpart of stream_reader: a batch is acked only after its handler returned. When
the handler fails, the batch is handed back (nak) with a growing delay and comes back once it
is due; a message whose ack never arrived (the process died) comes back after the consumer's
ack wait. The consumer keeps no limit on deliveries, so nothing is dropped for failing often.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from nats.aio.msg import Msg
from nats.errors import ConnectionClosedError, NoServersError, TimeoutError as NatsTimeoutError
from nats.js.errors import FetchDisconnectedError

logger = logging.getLogger(__name__)

_NATS_ERROR_PAUSE_SECONDS = 5.0
_RETRY_BASE_DELAY_SECONDS = 1.0
_RETRY_MAX_DELAY_SECONDS = 60.0

BatchHandler = Callable[[list[Msg]], Awaitable[None]]


class PullSubscription:
    """What consume_jetstream needs of nats-py's pull subscription (a fake in the tests)."""

    async def fetch(self, batch: int, timeout: float) -> list[Msg]: ...


async def consume_jetstream(
    subscription: PullSubscription,
    name: str,
    handle: BatchHandler,
    batch: int,
    fetch_timeout: float,
    on_cycle: Callable[[], None] = lambda: None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Loop forever: fetch a batch, hand it to `handle`, ack only if it returned.

    `on_cycle` runs after every cycle that left nothing behind (a batch acked or an empty
    fetch), so a caller can tell a working consumer from a stuck or disconnected one.
    """
    retry_delay = _RETRY_BASE_DELAY_SECONDS

    while True:
        try:
            messages = await subscription.fetch(batch, timeout=fetch_timeout)
        except FetchDisconnectedError:
            # A subclass of TimeoutError: the connection dropped while waiting. Not a quiet stream.
            logger.warning("consumer %s: disconnected while fetching, retrying in %.0fs", name, _NATS_ERROR_PAUSE_SECONDS)
            await sleep(_NATS_ERROR_PAUSE_SECONDS)
            continue
        except NatsTimeoutError:
            on_cycle()
            continue
        except (ConnectionClosedError, NoServersError):
            raise  # the connection is gone for good: let the supervisor start over
        except Exception as exc:
            logger.error("consumer %s: fetch failed: %s, retrying in %.0fs", name, exc, _NATS_ERROR_PAUSE_SECONDS)
            await sleep(_NATS_ERROR_PAUSE_SECONDS)
            continue

        try:
            await handle(messages)
        except Exception as exc:
            logger.error(
                "consumer %s: batch of %d failed, handed back, retrying in %.0fs: %s",
                name, len(messages), retry_delay, exc,
            )
            await _hand_back(messages, retry_delay, name)
            await sleep(retry_delay)
            retry_delay = min(retry_delay * 2, _RETRY_MAX_DELAY_SECONDS)
            continue

        await _ack(messages, name)
        retry_delay = _RETRY_BASE_DELAY_SECONDS
        on_cycle()


async def _hand_back(messages: list[Msg], delay: float, name: str) -> None:
    for message in messages:
        try:
            await message.nak(delay=delay)
        except Exception as exc:
            # Not handed back: the consumer's ack wait brings it back instead.
            logger.warning("consumer %s: nak failed: %s", name, exc)
            return


async def _ack(messages: list[Msg], name: str) -> None:
    for message in messages:
        try:
            await message.ack()
        except Exception as exc:
            # Redelivered after the ack wait; the write is not repeated (app.dedup, idempotent events).
            logger.warning("consumer %s: ack failed, the batch will be redelivered: %s", name, exc)
            return
