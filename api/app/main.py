"""Maestro API: HTTP only.

Stream consumers, the alert evaluator and the scheduled jobs run in the worker
(`python -m app.worker`); /health reports on both.
"""
import logging
import time
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import Depends, FastAPI

from app.about import router as about_router
from app.alert_channels import router as alert_channels_router
from app.alerts import router as alerts_router
from app.anomalies import router as anomalies_router
from app.analysis import router as analysis_router
from app.audit_routes import router as audit_router
from app.auth import require_active_user
from app.auth import router as auth_router
from app.auth_db import bootstrap_legacy_admin
from app.clickhouse import ClickHouseReader, ClickHouseWriter, create_client
from app.config import check_jwt_secret, settings
from app.db import check_database_url, check_schema_is_current, dispose_engine
from app.db_connections import router as db_connections_router
from app.events import router as events_router
from app.forecasts import router as forecasts_router
from app.health import router as health_router
from app.inventory import router as inventory_router
from app.logging_config import configure_logging
from app.logs import router as logs_router
from app.meta import router as meta_router
from app.metrics import router as metrics_router
from app.open_alerts import router as open_alerts_router
from app.quiet_routes import router as quiet_router
from app.registry import router as registry_router
from app.scoped_alerts import router as scoped_alerts_router
from app.security import router as security_router
from app.server_directory import router as server_directory_router
from app.servers import router as servers_router
from app.users import router as users_router
from app.vulnerabilities import router as vuln_router

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fails startup on a missing or public token secret, before anything else runs.
    check_jwt_secret(settings.jwt_secret)

    # Postgres must be reachable and at the schema this code expects (Alembic).
    check_database_url(settings.database_url)
    await check_schema_is_current()
    await bootstrap_legacy_admin()

    # Single shared ClickHouse client — Writer and Reader reuse the same connection pool.
    ch_client = await create_client()
    app.state.ch_client = ch_client
    app.state.ch_reader = ClickHouseReader(ch_client)
    app.state.ch_writer = ClickHouseWriter(ch_client)

    # Shared Redis client: vulnerability cache, DB connection snapshots and the worker's health report.
    redis = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
    app.state.vuln_redis = redis
    app.state.started_at = time.monotonic()

    yield

    await ch_client.close()
    await redis.aclose()
    await dispose_engine()
    logger.info("app: ClickHouse, Redis and Postgres connections closed")


app = FastAPI(title="Maestro API", lifespan=lifespan)

_protected = [Depends(require_active_user)]

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(meta_router, dependencies=_protected)
app.include_router(about_router, dependencies=_protected)
app.include_router(users_router, dependencies=_protected)
app.include_router(audit_router, dependencies=_protected)
app.include_router(servers_router, dependencies=_protected)
app.include_router(server_directory_router, dependencies=_protected)
app.include_router(metrics_router, dependencies=_protected)
app.include_router(logs_router, dependencies=_protected)
app.include_router(security_router, dependencies=_protected)
app.include_router(inventory_router, dependencies=_protected)
# Before the per-server alert routes, whose /alerts/{server_id}/... paths would also match /alerts/rules/...
app.include_router(scoped_alerts_router, dependencies=_protected)
app.include_router(quiet_router, dependencies=_protected)
app.include_router(alert_channels_router, dependencies=_protected)
app.include_router(open_alerts_router, dependencies=_protected)
app.include_router(alerts_router, dependencies=_protected)
app.include_router(forecasts_router, dependencies=_protected)
app.include_router(anomalies_router, dependencies=_protected)
app.include_router(events_router, dependencies=_protected)
app.include_router(analysis_router, dependencies=_protected)
app.include_router(registry_router, dependencies=_protected)
app.include_router(vuln_router, dependencies=_protected)
app.include_router(db_connections_router, dependencies=_protected)


@app.get("/")
async def root():
    return {"message": "Maestro API is running"}
