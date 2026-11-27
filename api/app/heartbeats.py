"""Each server's last heartbeat, wherever the agents send it.

On Redis the worker keeps it in the `maestro:server_heartbeats` hash (app.heartbeat). On NATS the
`MAESTRO_HEARTBEAT` stream keeps one message per server, read with a direct get (ADR-015), so it
is never copied anywhere. With `transport: both` the newest of the two counts, per server.

Every reader gets the same JSON text the Redis hash holds (app.heartbeat.heartbeat_state):
`last_seen`, `agent_version`, `watched_logs`, `inventory`. Each process opens one source at
startup (`open_source`) and the code reads it through `source()`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Protocol

import redis.asyncio as aioredis
from nats.aio.client import Client
from nats.js.errors import NotFoundError

from app import nats_client
from app.config import settings
from app.heartbeat import heartbeat_state
from app.nats_ingest import Unreadable, open_envelope

logger = logging.getLogger(__name__)


class HeartbeatSource(Protocol):
    async def all(self) -> dict[str, str]: ...

    async def get(self, server_id: str) -> str | None: ...

    async def get_many(self, server_ids: list[str]) -> list[str | None]: ...

    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class RedisHeartbeats:
    def __init__(self, redis: aioredis.Redis, owned: bool = True) -> None:
        self._redis = redis
        self._owned = owned

    async def all(self) -> dict[str, str]:
        return await self._redis.hgetall(settings.heartbeat_state_key)

    async def get(self, server_id: str) -> str | None:
        return await self._redis.hget(settings.heartbeat_state_key, server_id)

    async def get_many(self, server_ids: list[str]) -> list[str | None]:
        if not server_ids:
            return []
        return await self._redis.hmget(settings.heartbeat_state_key, server_ids)

    async def ping(self) -> None:
        await self._redis.ping()

    async def close(self) -> None:
        if self._owned:
            await self._redis.aclose()


class NatsHeartbeats:
    """Reads MAESTRO_HEARTBEAT. Connects on first use and again after a failed attempt, so a
    process starts even when NATS is unreachable."""

    def __init__(self, user: str, nkey_file: str, process: str) -> None:
        self._user = user
        self._nkey_file = nkey_file
        self._process = process
        self._client: Client | None = None
        self._connecting = asyncio.Lock()

    async def _js(self):
        if self._client is None:
            async with self._connecting:
                if self._client is None:
                    self._client = await nats_client.connect(self._user, self._nkey_file, self._process)
        return self._client.jetstream()

    async def all(self) -> dict[str, str]:
        js = await self._js()
        info = await js.stream_info(nats_client.HEARTBEAT_STREAM, subjects_filter=nats_client.HEARTBEAT_SUBJECTS)
        servers = sorted(
            server for subject in (info.state.subjects or {}) if (server := nats_client.subject_server(subject))
        )
        states = await self.get_many(servers)
        return {server: state for server, state in zip(servers, states) if state is not None}

    async def get(self, server_id: str) -> str | None:
        js = await self._js()
        subject = nats_client.heartbeat_subject(server_id)
        try:
            message = await js.get_msg(nats_client.HEARTBEAT_STREAM, subject=subject, direct=True)
        except NotFoundError:
            return None
        return state_from_message(subject, message.data)

    async def get_many(self, server_ids: list[str]) -> list[str | None]:
        return list(await asyncio.gather(*(self.get(server_id) for server_id in server_ids)))

    async def ping(self) -> None:
        js = await self._js()
        await js.stream_info(nats_client.HEARTBEAT_STREAM)

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.close()


def state_from_message(subject: str, payload: bytes | None) -> str | None:
    """The heartbeat state of one stream message, or None when it is unusable."""
    try:
        envelope = open_envelope(subject, payload or b"")
        if envelope.type != "heartbeat" or not isinstance(envelope.data, dict):
            raise Unreadable(f"type '{envelope.type}' on {subject}")
        if envelope.data.get("server_id", envelope.server_id) != envelope.server_id:
            raise Unreadable(f"heartbeat of '{envelope.data.get('server_id')}' on {subject}")
        return json.dumps(heartbeat_state(envelope.data))
    except Exception as exc:
        logger.warning("heartbeats: unusable message on %s: %s", subject, exc)
        return None


def _last_seen(state: str | None) -> datetime | None:
    if not state:
        return None
    try:
        return datetime.fromisoformat(json.loads(state)["last_seen"])
    except (ValueError, KeyError, TypeError):
        return None


def newest(states: list[str | None]) -> str | None:
    """The state with the latest `last_seen`; an unreadable one only when nothing else is there."""
    dated = [(seen, state) for state in states if (seen := _last_seen(state)) is not None]
    if dated:
        return max(dated, key=lambda pair: pair[0])[1]
    return next((state for state in states if state), None)


class MergedHeartbeats:
    """The newest heartbeat of each server across several sources. One source failing leaves
    the others' answer (logged); all of them failing raises the first error."""

    def __init__(self, sources: list[HeartbeatSource], names: list[str]) -> None:
        self._sources = sources
        self._names = names

    @property
    def sources(self) -> list[HeartbeatSource]:
        return list(self._sources)

    async def _ask(self, call):
        results = await asyncio.gather(*(call(source) for source in self._sources), return_exceptions=True)
        answers = []
        for name, result in zip(self._names, results):
            if isinstance(result, BaseException):
                if isinstance(result, asyncio.CancelledError):
                    raise result
                logger.warning("heartbeats: %s unavailable: %s", name, result)
                continue
            answers.append(result)
        if not answers:
            raise next(r for r in results if isinstance(r, BaseException))
        return answers

    async def all(self) -> dict[str, str]:
        answers = await self._ask(lambda source: source.all())
        servers = sorted({server for answer in answers for server in answer})
        merged = {server: newest([answer.get(server) for answer in answers]) for server in servers}
        return {server: state for server, state in merged.items() if state is not None}

    async def get(self, server_id: str) -> str | None:
        return newest(await self._ask(lambda source: source.get(server_id)))

    async def get_many(self, server_ids: list[str]) -> list[str | None]:
        answers = await self._ask(lambda source: source.get_many(server_ids))
        return [newest([answer[i] for answer in answers]) for i in range(len(server_ids))]

    async def ping(self) -> None:
        for source in self._sources:
            await source.ping()

    async def close(self) -> None:
        for source in self._sources:
            await source.close()


_source: HeartbeatSource | None = None


def build_source(user: str, nkey_file: str, process: str, redis: aioredis.Redis | None = None) -> HeartbeatSource:
    """The source for `settings.transport`. `redis`, when given, is shared and not closed here."""
    def redis_source() -> RedisHeartbeats:
        if redis is not None:
            return RedisHeartbeats(redis, owned=False)
        return RedisHeartbeats(aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None))

    if settings.transport == "redis":
        return redis_source()
    nats_client.check_configured()
    nats = NatsHeartbeats(user, nkey_file, process)
    if settings.transport == "nats":
        return nats
    return MergedHeartbeats([redis_source(), nats], ["redis", "nats"])


def open_source(user: str, nkey_file: str, process: str, redis: aioredis.Redis | None = None) -> HeartbeatSource:
    global _source
    _source = build_source(user, nkey_file, process, redis)
    return _source


def use_source(source: HeartbeatSource | None) -> None:
    """Set the source directly (tests)."""
    global _source
    _source = source


def source() -> HeartbeatSource:
    if _source is None:
        raise RuntimeError("no heartbeat source: call heartbeats.open_source() at startup")
    return _source


def dependency() -> HeartbeatSource:
    """The process's source, for routes (`Depends(heartbeats.dependency)`; tests override it)."""
    return source()


async def ping_nats() -> None:
    """Whether this process reaches the heartbeat stream; for /health."""
    current = source()
    candidates = current.sources if isinstance(current, MergedHeartbeats) else [current]
    nats = next((c for c in candidates if isinstance(c, NatsHeartbeats)), None)
    if nats is None:
        raise RuntimeError("this process reads no heartbeats from NATS")
    await nats.ping()


async def close_source() -> None:
    global _source
    current, _source = _source, None
    if current is not None:
        await current.close()
