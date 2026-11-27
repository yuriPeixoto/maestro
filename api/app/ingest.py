"""Maestro ingest: the NATS consumers that write what the agents send (ADR-015).

`python -m app.ingest`. A process of its own, so it can run on the API host or on the NATS host by
configuration alone (it needs ClickHouse, Postgres and NATS, not Redis). It reads three durable
pull consumers, defined in deploy/nats/consumers/: metrics and logs into ClickHouse, written once
whichever path they came by (app.dedup), and the agents' events into Postgres. Heartbeats are not
consumed: their stream keeps each server's last one (app.heartbeats).

Several ingest processes may run against the same consumers: each message goes to one of them.
Every few seconds the process writes how its tasks are doing to Postgres, for the API's /health.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from nats.aio.client import Client

from app import db, dedup, nats_client, worker_health
from app.clickhouse import ClickHouseWriter, create_client
from app.config import settings
from app.jetstream_reader import BatchHandler, consume_jetstream
from app.logging_config import configure_logging
from app.nats_ingest import events_handler, logs_handler, metrics_handler
from app.task_health import TaskRegistry, supervise

logger = logging.getLogger(__name__)

PROCESS = worker_health.INGEST_PROCESS

# A consumer beats at least once per fetch (5 s); two minutes without one means its writes keep
# failing or NATS is unreachable.
_CONSUMER_STALE_SECONDS = 120
_FETCH_TIMEOUT_SECONDS = 5.0
# Messages per fetch. An agent message holds up to 50 metrics, or up to 500 log lines.
_METRICS_BATCH = 100
_LOGS_BATCH = 20
_EVENTS_BATCH = 50


def _consumer(client: Client, stream: str, durable: str, handle: BatchHandler, batch: int):
    async def run(beat) -> None:
        subscription = await client.jetstream().pull_subscribe_bind(durable=durable, stream=stream)
        logger.info("ingest: reading consumer %s on %s", durable, stream)
        try:
            await consume_jetstream(subscription, durable, handle, batch, _FETCH_TIMEOUT_SECONDS, beat)
        finally:
            with contextlib.suppress(Exception):
                await subscription.unsubscribe()

    return run


async def run_ingest(stop: asyncio.Event) -> None:
    if settings.transport == "redis":
        raise RuntimeError("MAESTRO_TRANSPORT is 'redis': nothing for the ingest process to read")
    db.set_application_name("maestro-ingest")
    db.check_database_url(settings.database_url)
    await db.check_schema_is_current()
    ch_client = await create_client()
    writer = ClickHouseWriter(ch_client)
    client = await nats_client.connect(nats_client.WORKER_USER, settings.nats_worker_nkey_file, "maestro-ingest")

    registry = TaskRegistry()
    consumers = [
        (nats_client.METRICS_CONSUMER, nats_client.METRICS_STREAM, metrics_handler(writer), _METRICS_BATCH),
        (nats_client.LOGS_CONSUMER, nats_client.LOGS_STREAM, logs_handler(writer), _LOGS_BATCH),
        (nats_client.EVENTS_CONSUMER, nats_client.EVENTS_STREAM, events_handler(), _EVENTS_BATCH),
    ]
    tasks = []
    for durable, stream, handle, batch in consumers:
        registry.register(durable, stale_after_seconds=_CONSUMER_STALE_SECONDS)
        run = _consumer(client, stream, durable, handle, batch)
        tasks.append(asyncio.create_task(
            supervise(registry, durable, lambda run=run, name=durable: run(registry.beater(name))), name=durable,
        ))
    tasks.append(asyncio.create_task(worker_health.publish_forever(PROCESS, registry), name="health-publisher"))
    tasks.append(asyncio.create_task(dedup.log_counts_forever(PROCESS), name="ingest-counts"))
    logger.info("ingest: %d consumers started", len(consumers))

    try:
        await stop.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await worker_health.withdraw(PROCESS)
        with contextlib.suppress(Exception):
            await client.drain()
        await ch_client.close()
        await db.dispose_engine()
        logger.info("ingest: stopped")


async def _main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await run_ingest(stop)


def main() -> None:
    configure_logging()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main())


if __name__ == "__main__":
    main()
