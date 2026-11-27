"""What the ingest consumers do with each NATS message (docs/nats.md has the envelope).

The subject is the identity (ADR-015): the server comes from `maestro.ingest.<server>.<kind>`, and
a message whose payload names another server is dropped. A message that cannot be read never will
be, so it is acked with its batch and logged, as on the Redis path.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from nats.aio.msg import Msg

from app import agent_store, dedup
from app.clickhouse import ClickHouseWriter, LogRow, MetricRow
from app.consumer import parse_agent_timestamp, parse_metric
from app.jetstream_reader import BatchHandler
from app.nats_client import subject_server

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Envelope:
    msg_id: UUID | None
    server_id: str
    type: str
    sent_at: datetime
    data: Any


class Unreadable(ValueError):
    pass


def open_envelope(subject: str, payload: bytes) -> Envelope:
    """The message as the agent sent it. Raises Unreadable, saying why, when it cannot be used."""
    server_id = subject_server(subject)
    if server_id is None:
        raise Unreadable(f"not an ingest subject: {subject}")
    try:
        body = json.loads(payload)
        claimed = body["server_id"]
        message_type = body["type"]
        sent_at = parse_agent_timestamp(body["sent_at"])
        data = body["data"]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise Unreadable(f"bad envelope: {exc!r}") from exc
    if claimed != server_id:
        raise Unreadable(f"payload names server '{claimed}' on {subject}")
    return Envelope(dedup.parse_id(body.get("id")), server_id, message_type, sent_at, data)


def _opened(message: Msg, kind: str) -> Envelope | None:
    try:
        envelope = open_envelope(message.subject, message.data)
    except Unreadable as exc:
        logger.warning("ingest %s: dropped a message: %s", kind, exc)
        return None
    if envelope.type != kind:
        logger.warning("ingest %s: dropped a message of type '%s' on %s", kind, envelope.type, message.subject)
        return None
    return envelope


def metric_rows(envelope: Envelope) -> list[MetricRow]:
    rows = []
    for raw in envelope.data or []:
        try:
            row = parse_metric(raw)
        except Exception as exc:
            logger.warning("ingest metrics: failed to parse a metric: %s — raw: %.200s", exc, raw)
            continue
        if row.server_id != envelope.server_id:
            logger.warning("ingest metrics: dropped a metric of '%s' sent by '%s'", row.server_id, envelope.server_id)
            continue
        rows.append(row)
    return rows


def log_rows(envelope: Envelope) -> list[LogRow]:
    data = envelope.data or {}
    log_file = data.get("log_file")
    rows = []
    for line in data.get("lines") or []:
        try:
            rows.append(LogRow(
                server_id=envelope.server_id,
                log_file=log_file,
                timestamp=parse_agent_timestamp(line["timestamp"]),
                line=line["line"],
            ))
        except Exception as exc:
            logger.warning("ingest logs: failed to parse a line of %s: %s", log_file, exc)
    if not isinstance(log_file, str) or not log_file:
        logger.warning("ingest logs: dropped %d lines without a log file from '%s'", len(rows), envelope.server_id)
        return []
    return rows


def metrics_handler(writer: ClickHouseWriter) -> BatchHandler:
    async def handle(messages: list[Msg]) -> None:
        items = [(e.msg_id, metric_rows(e)) for m in messages if (e := _opened(m, "metrics")) is not None]
        await dedup.write_once(items, "nats", "metrics", writer.insert_batch)

    return handle


def logs_handler(writer: ClickHouseWriter) -> BatchHandler:
    async def handle(messages: list[Msg]) -> None:
        items = [(e.msg_id, log_rows(e)) for m in messages if (e := _opened(m, "logs")) is not None]
        await dedup.write_once(items, "nats", "logs", writer.insert_log_batch)

    return handle


async def apply_event(envelope: Envelope) -> None:
    """Record one event. Writes are idempotent and keep the newest, so redelivery is harmless."""
    data = envelope.data if isinstance(envelope.data, dict) else {}
    match envelope.type:
        case "agent_registered":
            await agent_store.record_registration(
                envelope.server_id,
                hostname=str(data.get("hostname") or envelope.server_id),
                os=str(data.get("os") or "unknown"),
                tags=[str(tag) for tag in data.get("tags") or []],
                agent_version=str(data.get("agent_version") or "unknown"),
                sent_at=envelope.sent_at,
            )
        case "agent_deregistered":
            await agent_store.record_deregistration(envelope.server_id, envelope.sent_at)
        case "packages":
            await agent_store.save_packages(envelope.server_id, data, envelope.sent_at)
        case "db_connections":
            db_type = data.get("db_type")
            if not isinstance(db_type, str) or not db_type:
                logger.warning("ingest events: db_connections without db_type from '%s'", envelope.server_id)
                return
            await agent_store.save_db_snapshot(
                envelope.server_id, db_type, list(data.get("connections") or []), envelope.sent_at,
            )
        case other:
            logger.warning("ingest events: unknown event type '%s' from '%s'", other, envelope.server_id)


def events_handler() -> BatchHandler:
    async def handle(messages: list[Msg]) -> None:
        for message in messages:
            try:
                envelope = open_envelope(message.subject, message.data)
            except Unreadable as exc:
                logger.warning("ingest events: dropped a message: %s", exc)
                continue
            await apply_event(envelope)

    return handle
