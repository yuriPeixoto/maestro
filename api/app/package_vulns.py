"""Match the OS packages reported by an agent against distribution advisories on OSV.dev.

Version comparison happens on the OSV side using the distribution's own rules, so
backported fixes are honoured: a package is only flagged when the installed
version is really older than the one the distribution fixed.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from app import osv

logger = logging.getLogger(__name__)

_BATCH_SIZE = 1000  # OSV limit of queries per querybatch call
_MAX_PAGES_PER_PACKAGE = 20
_CONCURRENT_QUERIES = 8
# The kernel alone has thousands of fixed CVEs between two point releases;
# past this many, one more row adds nothing to "this package must be upgraded".
_MAX_VULNS_PER_PACKAGE = 50
_UNSCORED = -1.0


async def scan_packages(client: httpx.AsyncClient, ecosystem: str, packages: list[dict]) -> list[dict]:
    """Return one entry per fixable vulnerability, most severe first.

    Only vulnerabilities the distribution has already fixed are returned: those
    are the ones an upgrade resolves. Open issues without a fix are left out.
    Each package contributes at most its _MAX_VULNS_PER_PACKAGE most severe entries.
    """
    valid = [p for p in packages if p.get("name") and p.get("version")]
    affected = await _packages_with_vulns(client, ecosystem, valid)
    if not affected:
        return []

    limiter = asyncio.Semaphore(_CONCURRENT_QUERIES)

    async def query(package: dict) -> list[tuple[float, dict]]:
        async with limiter:
            try:
                return await _fixable_vulns(client, ecosystem, package)
            except httpx.HTTPError as exc:
                logger.warning("package_vulns: query %s@%s failed: %s", package["name"], package["version"], exc)
                return []

    scored = [entry for found in await asyncio.gather(*(query(p) for p in affected)) for entry in found]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _score, entry in scored]


async def _packages_with_vulns(client: httpx.AsyncClient, ecosystem: str, packages: list[dict]) -> list[dict]:
    """One cheap batched call to find which packages are worth a detailed query."""
    affected: list[dict] = []
    for start in range(0, len(packages), _BATCH_SIZE):
        batch = packages[start : start + _BATCH_SIZE]
        queries = [
            {"package": {"name": p["name"], "ecosystem": ecosystem}, "version": p["version"]} for p in batch
        ]
        resp = await client.post(osv.OSV_QUERYBATCH_URL, json={"queries": queries})
        resp.raise_for_status()
        results = resp.json().get("results") or []
        affected.extend(p for p, result in zip(batch, results) if result.get("vulns"))
    return affected


async def _fixable_vulns(client: httpx.AsyncClient, ecosystem: str, package: dict) -> list[tuple[float, dict]]:
    payload: dict = {"package": {"name": package["name"], "ecosystem": ecosystem}, "version": package["version"]}
    found: list[tuple[float, dict]] = []

    for _page in range(_MAX_PAGES_PER_PACKAGE):
        resp = await client.post(osv.OSV_QUERY_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()

        for vuln in data.get("vulns") or []:
            fixed = osv.fixed_version(vuln, ecosystem)
            if fixed is None:
                continue
            score = osv.score(vuln)
            found.append((
                score if score is not None else _UNSCORED,
                {
                    "runtime": package["name"],
                    "version": package["version"],
                    "cve_id": osv.cve_id(vuln),
                    "severity": osv.severity(vuln),
                    "summary": osv.summary(vuln),
                    "fixed_version": fixed,
                    "published_at": vuln.get("published"),
                },
            ))

        token = data.get("next_page_token")
        if not token:
            break
        payload["page_token"] = token

    found.sort(key=lambda item: item[0], reverse=True)
    if len(found) > _MAX_VULNS_PER_PACKAGE:
        logger.info(
            "package_vulns: %s@%s has %d fixable vulns — keeping the %d most severe",
            package["name"], package["version"], len(found), _MAX_VULNS_PER_PACKAGE,
        )
    return found[:_MAX_VULNS_PER_PACKAGE]
