from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import settings
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

OSV_QUERY_URL = "https://api.osv.dev/v1/query"

# Redis keys
_VULN_HASH = "maestro:vulns"          # HSET {server_id} -> JSON array
_LAST_SCAN_KEY = "maestro:vuln_scan_ts"  # last scan timestamp (epoch float)


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
    scanned_at_raw = await redis.get(_LAST_SCAN_KEY)

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
    """Background task: scans all registered servers for CVEs daily via OSV.dev."""
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        while True:
            try:
                await _scan_all(redis)
            except Exception as exc:
                logger.error("vuln_scanner: scan failed: %s", exc)
            await asyncio.sleep(settings.vuln_scan_interval_hours * 3600)
    finally:
        await redis.aclose()


async def _scan_all(redis: aioredis.Redis) -> None:
    server_ids = await redis.smembers(settings.agent_ids_key)
    if not server_ids:
        logger.info("vuln_scanner: no registered agents — skipping")
        return

    logger.info("vuln_scanner: scanning %d server(s)...", len(server_ids))

    async with httpx.AsyncClient(timeout=15) as client:
        for server_id in server_ids:
            try:
                await _scan_server(redis, client, server_id)
            except Exception as exc:
                logger.warning("vuln_scanner: server_id=%s error: %s", server_id, exc)

    now_iso = datetime.now(timezone.utc).isoformat()
    await redis.set(_LAST_SCAN_KEY, now_iso)
    logger.info("vuln_scanner: scan complete at %s", now_iso)


async def _scan_server(redis: aioredis.Redis, client: httpx.AsyncClient, server_id: str) -> None:
    hb_raw = await redis.hget(settings.heartbeat_state_key, server_id)
    if not hb_raw:
        return

    data = json.loads(hb_raw)
    inventory = data.get("inventory") or []
    if not inventory:
        return

    all_vulns: list[dict] = []

    for entry in inventory:
        name = (entry.get("name") or "").lower()
        version = entry.get("version") or ""
        if not version or version in ("unknown", "not found"):
            continue

        ecosystem = _ECOSYSTEM.get(name)
        if not ecosystem:
            continue

        try:
            found = await _query_osv(client, name, version, ecosystem)
            all_vulns.extend(found)
        except Exception as exc:
            logger.debug("vuln_scanner: osv query %s@%s failed: %s", name, version, exc)

    # Store results (even if empty — confirms the scan ran for this server).
    await redis.hset(_VULN_HASH, server_id, json.dumps(all_vulns))

    if all_vulns:
        logger.info("vuln_scanner: server_id=%s — %d vuln(s) found", server_id, len(all_vulns))


async def _query_osv(
    client: httpx.AsyncClient, name: str, version: str, ecosystem: str
) -> list[dict]:
    payload = {"package": {"name": name, "ecosystem": ecosystem}, "version": version}
    resp = await client.post(OSV_QUERY_URL, json=payload)
    resp.raise_for_status()

    data = resp.json()
    vulns_raw = data.get("vulns") or []

    results: list[dict] = []
    for v in vulns_raw:
        fixed = _extract_fixed_version(v)
        # Only show CVEs that have a known fix — per acceptance criteria.
        if fixed is None:
            continue

        cve_id = _extract_cve_id(v)
        severity = _extract_severity(v)
        results.append({
            "runtime": name,
            "version": version,
            "cve_id": cve_id,
            "severity": severity,
            "summary": v.get("summary") or v.get("id") or "No summary",
            "fixed_version": fixed,
            "published_at": v.get("published"),
        })

    return results


def _extract_cve_id(vuln: dict) -> str:
    for alias in vuln.get("aliases") or []:
        if alias.startswith("CVE-"):
            return alias
    return vuln.get("id", "UNKNOWN")


def _extract_severity(vuln: dict) -> str | None:
    severity_list = vuln.get("severity") or []
    for s in severity_list:
        score = s.get("score") or ""
        # CVSS v3 base score: first character encodes severity
        if "CVSS:3" in score.upper():
            # Extract base score from vector string
            parts = score.split("/")
            for p in parts:
                if p.startswith("AV:"):
                    break
            # Use database_specific.severity if available
        stype = s.get("type", "")
        if stype == "CVSS_V3":
            return _cvss3_severity(s.get("score", ""))
    db = (vuln.get("database_specific") or {})
    return db.get("severity")


def _cvss3_severity(score_str: str) -> str | None:
    # Parse the numerical base score from a CVSS v3 vector or plain float
    try:
        val = float(score_str)
    except ValueError:
        return None
    if val >= 9.0:
        return "critical"
    if val >= 7.0:
        return "high"
    if val >= 4.0:
        return "medium"
    return "low"


def _extract_fixed_version(vuln: dict) -> str | None:
    for affected in vuln.get("affected") or []:
        for rng in affected.get("ranges") or []:
            for event in rng.get("events") or []:
                fixed = event.get("fixed")
                if fixed:
                    return fixed
    return None
