"""Maestro's own connections to NATS (ADR-015), and the names the agents and the streams agree on.

Each process connects as one of Maestro's users, whose credential (an NKey seed file) only
reaches what that process needs: `maestro-worker` reads the ingest consumers and the last
heartbeats, `maestro-api` only the heartbeats. A user may only subscribe to its own reply inbox,
`_INBOX_<user>`, so the connection sets that prefix. Streams and consumers are infrastructure
(`deploy/nats/`): no Maestro process creates or changes them.
"""
from __future__ import annotations

import logging
import re
import ssl

import nats
from nats.aio.client import Client

from app.config import settings

logger = logging.getLogger(__name__)

WORKER_USER = "maestro-worker"
API_USER = "maestro-api"

METRICS_STREAM = "MAESTRO_METRICS"
LOGS_STREAM = "MAESTRO_LOGS"
EVENTS_STREAM = "MAESTRO_EVENTS"
HEARTBEAT_STREAM = "MAESTRO_HEARTBEAT"

# Durable pull consumers, defined in deploy/nats/consumers/.
METRICS_CONSUMER = "maestro-ingest-metrics"
LOGS_CONSUMER = "maestro-ingest-logs"
EVENTS_CONSUMER = "maestro-ingest-events"

HEARTBEAT_SUBJECTS = "maestro.ingest.*.heartbeat"
# maestro.ingest.<server>.<kind>: the server is one token of [a-z0-9_-] (deploy/nats/render-users.sh).
_INGEST_SUBJECT = re.compile(r"^maestro\.ingest\.([a-z0-9_-]+)\.(metrics|logs|events|heartbeat)$")

_CONNECT_TIMEOUT_SECONDS = 5
_RECONNECT_WAIT_SECONDS = 2


def subject_server(subject: str) -> str | None:
    """The server a message was published as, taken from its subject (never from the payload)."""
    match = _INGEST_SUBJECT.match(subject)
    return match.group(1) if match else None


def heartbeat_subject(server_id: str) -> str:
    return f"maestro.ingest.{server_id}.heartbeat"


def check_configured() -> None:
    if not settings.nats_url:
        raise RuntimeError(
            f"MAESTRO_TRANSPORT is '{settings.transport}', which reads NATS, but MAESTRO_NATS_URL is not set"
        )


def _tls() -> ssl.SSLContext | None:
    if not settings.nats_ca_file:
        return None
    return ssl.create_default_context(cafile=settings.nats_ca_file)


async def connect(user: str, nkey_file: str, process: str) -> Client:
    """Connect as `user`. Raises when NATS is unreachable at first; once connected, reconnects
    on its own for as long as it takes."""
    check_configured()

    async def on_error(exc: Exception) -> None:
        logger.warning("nats (%s): %s", process, exc)

    async def on_disconnected() -> None:
        logger.warning("nats (%s): disconnected, reconnecting", process)

    async def on_reconnected() -> None:
        logger.info("nats (%s): reconnected", process)

    return await nats.connect(
        servers=[settings.nats_url],
        name=process,
        nkeys_seed=nkey_file,
        inbox_prefix=f"_INBOX_{user}",
        tls=_tls(),
        connect_timeout=_CONNECT_TIMEOUT_SECONDS,
        reconnect_time_wait=_RECONNECT_WAIT_SECONDS,
        max_reconnect_attempts=-1,
        error_cb=on_error,
        disconnected_cb=on_disconnected,
        reconnected_cb=on_reconnected,
    )
