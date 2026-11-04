"""One low-priority child process for the CPU-heavy ML work.

Training, scoring, feature computation and forecasts run there instead of in the
worker's event loop, so stream consumers and the alert evaluator keep their pace
while a model trains. The child runs with a lower scheduling priority (nice) and is
created on first use. Functions sent to it must be importable at module level.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

# Lowest priority that still leaves room below it for anything else on the host.
_NICE_INCREMENT = 10

T = TypeVar("T")

_executor: ProcessPoolExecutor | None = None


def _lower_priority() -> None:
    nice = getattr(os, "nice", None)  # not available on Windows
    if nice is None:
        return
    try:
        nice(_NICE_INCREMENT)
    except OSError as exc:
        logger.warning("ml-pool: could not lower the priority: %s", exc)


def _get_executor() -> ProcessPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ProcessPoolExecutor(max_workers=1, initializer=_lower_priority)
    return _executor


async def run_in_ml_process(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run `fn(*args, **kwargs)` in the ML child process and wait for its result."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_executor(), partial(fn, *args, **kwargs))


def shutdown() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None
