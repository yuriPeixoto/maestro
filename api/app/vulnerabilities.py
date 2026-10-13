from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import osv
from app.config import settings
from app.package_vulns import scan_packages
from app.servers import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/security", tags=["security"])

# ── Ecosystem mapping ─────────────────────────────────────────────────────────

# Maps runtime names (as reported by the inventory collector) to OSV ecosystems.
_ECOSYSTEM: dict[str, str] = {
    "php":        "Packagist",
    "python":     "PyPI",
    "node":       "npm",
    "nodejs":     "npm",
    "ruby":       "RubyGems",
    "java":       "Maven",
    "nginx":      "OSS-Fuzz",
    "openssl":    "OSS-Fuzz",
    "curl":       "OSS-Fuzz",
    "libssl":     "OSS-Fuzz",
}

# Redis keys
_VULN_HASH = "maestro:vulns"          # HSET {server_id} -> JSON array
_LAST_SCAN_KEY = "maestro:vuln_scan_ts"  # timestamp of the last scan of any server (ISO 8601)
_SERVER_SCAN_HASH = "maestro:vuln_scan_ts_by_server"  # HSET {server_id} -> ISO 8601

# How often the scanner looks for servers that are due. A server seen for the
# first time is scanned on the next tick instead of waiting a full interval.
_SCHEDULER_TICK_SECONDS = 600
_OSV_TIMEOUT_SECONDS = 30


# ── Schemas ───────────────────────────────────────────────────────────────────

class VulnEntry(BaseModel):
    runtime: str
    version: str
    cve_id: str
    severity: str | None
    summary: str
    fixed_version: str | None
    published_at: str | None


class VulnerabilitiesResponse(BaseModel):
    server_id: str
    scanned_at: str | None
    vulnerabilities: list[VulnEntry]


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/{server_id}/vulnerabilities", response_model=VulnerabilitiesResponse)
async def get_vulnerabilities(server_id: str, request: Request) -> VulnerabilitiesResponse:
    redis: aioredis.Redis = request.app.state.vuln_redis
    raw = await redis.hget(_VULN_HASH, server_id)
    scanned_at_raw = await redis.hget(_SERVER_SCAN_HASH, server_id) or await redis.get(_LAST_SCAN_KEY)

    vulns: list[VulnEntry] = []
    if raw:
        try:
            vulns = [VulnEntry(**v) for v in json.loads(raw)]
        except Exception:
            pass

    return VulnerabilitiesResponse(
        server_id=server_id,
        scanned_at=scanned_at_raw,
        vulnerabilities=vulns,
    )


# ── Background scanner ────────────────────────────────────────────────────────

async def run_vulnerability_scanner() -> None:
    """Background task: scans each known server for CVEs via OSV.dev once per interval."""
    redis = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
    try:
        while True:
            try:
                await _scan_due_servers(redis)
            except Exception as exc:
                logger.error("vuln_scanner: scan failed: %s", exc)
            await asyncio.sleep(_SCHEDULER_TICK_SECONDS)
    finally:
        await redis.aclose()


async def _scan_due_servers(redis: aioredis.Redis) -> None:
    # Heartbeats are the source of truth for "which servers exist": an agent
    # that never registered through the API still reports inventory.
    server_ids = set(await redis.hkeys(settings.heartbeat_state_key))
    server_ids |= await redis.smembers(settings.agent_ids_key)

    last_scans = await redis.hgetall(_SERVER_SCAN_HASH)
    now = datetime.now(timezone.utc)
    due = [sid for sid in sorted(server_ids) if _is_due(last_scans.get(sid), now)]
    if not due:
        return

    logger.info("vuln_scanner: scanning %d server(s)...", len(due))
    async with httpx.AsyncClient(timeout=_OSV_TIMEOUT_SECONDS) as client:
        for server_id in due:
            try:
                await _scan_server(redis, client, server_id)
            except Exception as exc:
                logger.warning("vuln_scanner: server_id=%s error: %s", server_id, exc)
                continue
            now_iso = datetime.now(timezone.utc).isoformat()
            await redis.hset(_SERVER_SCAN_HASH, server_id, now_iso)
            await redis.set(_LAST_SCAN_KEY, now_iso)


def _is_due(last_scan_iso: str | None, now: datetime) -> bool:
    if not last_scan_iso:
        return True
    try:
        last_scan = datetime.fromisoformat(last_scan_iso)
    except ValueError:
        return True
    return (now - last_scan).total_seconds() >= settings.vuln_scan_interval_hours * 3600


async def _scan_server(redis: aioredis.Redis, client: httpx.AsyncClient, server_id: str) -> None:
    runtime_vulns = await _scan_runtimes(redis, client, server_id)
    package_vulns = await _scan_os_packages(redis, client, server_id)
    all_vulns = package_vulns + runtime_vulns

    # Store results (even if empty — confirms the scan ran for this server).
    await redis.hset(_VULN_HASH, server_id, json.dumps(all_vulns))

    if all_vulns:
        logger.info(
            "vuln_scanner: server_id=%s — %d vuln(s) found (%d in OS packages)",
            server_id, len(all_vulns), len(package_vulns),
        )


async def _scan_runtimes(redis: aioredis.Redis, client: httpx.AsyncClient, server_id: str) -> list[dict]:
    hb_raw = await redis.hget(settings.heartbeat_state_key, server_id)
    if not hb_raw:
        return []

    found: list[dict] = []
    for entry in json.loads(hb_raw).get("inventory") or []:
        name = (entry.get("name") or "").lower()
        version = entry.get("version") or ""
        if not version or version in ("unknown", "not found"):
            continue

        ecosystem = _ECOSYSTEM.get(name)
        if not ecosystem:
            continue

        try:
            found.extend(await _query_osv(client, name, version, ecosystem))
        except Exception as exc:
            logger.debug("vuln_scanner: osv query %s@%s failed: %s", name, version, exc)
    return found


async def _scan_os_packages(redis: aioredis.Redis, client: httpx.AsyncClient, server_id: str) -> list[dict]:
    raw = await redis.hget(settings.packages_key, server_id)
    if not raw:
        return []

    snapshot = json.loads(raw)
    ecosystem = snapshot.get("ecosystem")
    packages = snapshot.get("packages") or []
    if not ecosystem or not packages:
        return []
    return await scan_packages(client, ecosystem, packages)


async def _query_osv(
    client: httpx.AsyncClient, name: str, version: str, ecosystem: str
) -> list[dict]:
    payload = {"package": {"name": name, "ecosystem": ecosystem}, "version": version}
    resp = await client.post(osv.OSV_QUERY_URL, json=payload)
    resp.raise_for_status()

    results: list[dict] = []
    for v in resp.json().get("vulns") or []:
        fixed = osv.fixed_version(v)
        # Only show CVEs that have a known fix — per acceptance criteria.
        if fixed is None:
            continue

        results.append({
            "runtime": name,
            "version": version,
            "cve_id": osv.cve_id(v),
            "severity": osv.severity(v),
            "summary": osv.summary(v),
            "fixed_version": fixed,
            "published_at": v.get("published"),
        })

    return results
