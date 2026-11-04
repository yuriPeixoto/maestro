"""Maestro worker: stream consumers, the alert evaluator and the scheduled jobs.

Runs apart from the API (`python -m app.worker`), so a job that hogs the CPU or
hangs cannot stall the HTTP side, and the API keeps answering while the worker
restarts. Run exactly one: a second worker would evaluate every alert twice.

Each task is restarted when it stops (task_health.supervise). Every few seconds the
worker publishes how its tasks are doing to Redis, where the API's /health reads it.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from pathlib import Path

import redis.asyncio as aioredis

from app import worker_health
from app.alert_evaluator import EVAL_INTERVAL_SECONDS, run_alert_evaluator
from app.clickhouse import ClickHouseReader, ClickHouseWriter, create_client
from app.config import settings
from app.consumer import run_consumer
from app.correlation_analyzer import run_correlation_analyzer
from app.feature_engineering import run_feature_pipeline
from app.forecast_scheduler import run_forecast_scheduler
from app.heartbeat import run_heartbeat_consumer
from app.log_consumer import run_log_consumer
from app.logging_config import configure_logging
from app.ml import pool
from app.ml.anomaly_detector import run_anomaly_detector
from app.ml.model_store import ModelStore
from app.task_health import TaskRegistry, supervise
from app.vulnerabilities import run_vulnerability_scanner

logger = logging.getLogger(__name__)

# A consumer beats at least once per blocking read (5–10 s); two minutes without
# one means its inserts keep failing. The evaluator gets five of its cycles.
_CONSUMER_STALE_SECONDS = 120
_EVALUATOR_STALE_SECONDS = EVAL_INTERVAL_SECONDS * 5


async def run_worker(stop: asyncio.Event) -> None:
    ch_client = await create_client()
    writer = ClickHouseWriter(ch_client)
    reader = ClickHouseReader(ch_client)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)

    store = ModelStore(Path(settings.ml_models_dir))
    store.load_all()

    registry = TaskRegistry()

    def watched(name: str, stale_after: float, run):
        registry.register(name, stale_after_seconds=stale_after)
        return name, lambda: run(registry.beater(name))

    def unwatched(name: str, run):
        registry.register(name)
        return name, run

    task_specs = [
        watched("metrics-consumer", _CONSUMER_STALE_SECONDS, lambda beat: run_consumer(writer, beat)),
        watched("heartbeat-consumer", _CONSUMER_STALE_SECONDS, run_heartbeat_consumer),
        watched("log-consumer", _CONSUMER_STALE_SECONDS, lambda beat: run_log_consumer(writer, beat)),
        watched("alert-evaluator", _EVALUATOR_STALE_SECONDS, lambda beat: run_alert_evaluator(reader, writer, beat)),
        unwatched("feature-pipeline", lambda: run_feature_pipeline(reader, writer)),
        unwatched("anomaly-detector", lambda: run_anomaly_detector(reader, writer, store)),
        unwatched("forecast-scheduler", lambda: run_forecast_scheduler(reader)),
        unwatched("correlation-analyzer", lambda: run_correlation_analyzer(reader, writer)),
        unwatched("vuln-scanner", run_vulnerability_scanner),
    ]
    tasks = [asyncio.create_task(supervise(registry, name, run), name=name) for name, run in task_specs]
    tasks.append(asyncio.create_task(
        worker_health.publish_forever(registry, redis, settings.worker_health_key), name="health-publisher",
    ))
    logger.info("worker: %d supervised tasks started", len(task_specs))

    try:
        await stop.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        pool.shutdown()
        # Leave no report behind: the API should see the worker gone at once.
        with contextlib.suppress(Exception):
            await redis.delete(settings.worker_health_key)
        await redis.aclose()
        await ch_client.close()
        logger.info("worker: stopped")


async def _main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Supervisor and systemd stop with SIGTERM. Windows has no signal handlers in
        # the event loop; Ctrl+C still raises KeyboardInterrupt there.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await run_worker(stop)


def main() -> None:
    configure_logging()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main())


if __name__ == "__main__":
    main()
