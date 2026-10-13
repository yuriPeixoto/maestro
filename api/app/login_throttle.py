"""Slows down password guessing on the login endpoint.

State lives in memory: the API runs as a single process (see main.py lifespan),
and losing the counters on restart only gives an attacker a fresh window.
Failures are counted per identifier typed on the form, not per client address —
behind a reverse proxy the address is whatever the proxy forwards.
"""
from __future__ import annotations

import time

MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60

_failures: dict[str, list[float]] = {}


def _key(identifier: str) -> str:
    return identifier.strip().lower()


def _recent(identifier: str, now: float) -> list[float]:
    key = _key(identifier)
    recent = [t for t in _failures.get(key, []) if now - t < WINDOW_SECONDS]
    if recent:
        _failures[key] = recent
    else:
        _failures.pop(key, None)
    return recent


def seconds_until_allowed(identifier: str) -> int:
    """0 when a login attempt may proceed; otherwise how long the caller must wait."""
    now = time.monotonic()
    recent = _recent(identifier, now)
    if len(recent) < MAX_FAILURES:
        return 0
    return max(1, int(WINDOW_SECONDS - (now - recent[0])))


def record_failure(identifier: str) -> None:
    now = time.monotonic()
    _failures[_key(identifier)] = [*_recent(identifier, now), now]


def reset(identifier: str) -> None:
    _failures.pop(_key(identifier), None)
