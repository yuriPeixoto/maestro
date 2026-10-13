"""
Unit tests for the OS package advisory scan (cvss.py, osv.py, package_vulns.py).

OSV.dev is replaced by an httpx.MockTransport, so the tests never hit the network.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app import cvss, osv, package_vulns
from app.package_vulns import scan_packages

ECOSYSTEM = "Debian:12"


def _vuln(vuln_id: str, fixed: str | None, vector: str | None = None, ecosystem: str = ECOSYSTEM) -> dict:
    events = [{"introduced": "0"}]
    if fixed:
        events.append({"fixed": fixed})
    record: dict = {
        "id": vuln_id,
        "upstream": [vuln_id.removeprefix("DEBIAN-")],
        "details": f"Details of {vuln_id}\nsecond line",
        "published": "2026-01-01T00:00:00Z",
        "affected": [{"package": {"name": "pkg", "ecosystem": ecosystem}, "ranges": [{"events": events}]}],
    }
    if vector:
        record["severity"] = [{"type": "CVSS_V3", "score": vector}]
    return record


# ── CVSS ─────────────────────────────────────────────────────────────────────

class TestCvssBaseScore:
    @pytest.mark.parametrize(
        ("vector", "expected"),
        [
            ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),
            ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N", 7.5),
            ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", 10.0),
            ("CVSS:3.1/AV:L/AC:H/PR:L/UI:N/S:U/C:L/I:L/A:N", 3.6),
            ("CVSS:3.0/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:L", 8.3),
            ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N", 0.0),
        ],
    )
    def test_known_vectors(self, vector: str, expected: float) -> None:
        assert cvss.base_score(vector) == expected

    @pytest.mark.parametrize("vector", ["", "7.5", "CVSS:4.0/AV:N/AC:L", "CVSS:3.1/AV:N/AC:L"])
    def test_unsupported_or_incomplete_vector(self, vector: str) -> None:
        assert cvss.base_score(vector) is None

    def test_severity_labels(self) -> None:
        assert [cvss.severity_label(s) for s in (9.8, 7.5, 4.0, 3.9)] == ["critical", "high", "medium", "low"]


# ── OSV record helpers ───────────────────────────────────────────────────────

class TestOsvHelpers:
    def test_cve_id_from_upstream(self) -> None:
        assert osv.cve_id(_vuln("DEBIAN-CVE-2025-58098", "2.4.66-1~deb12u1")) == "CVE-2025-58098"

    def test_fixed_version_ignores_other_ecosystems(self) -> None:
        record = _vuln("DEBIAN-CVE-2025-1", "1.0", ecosystem="Debian:13")
        assert osv.fixed_version(record, ECOSYSTEM) is None
        assert osv.fixed_version(record) == "1.0"

    def test_summary_falls_back_to_first_line_of_details(self) -> None:
        assert osv.summary(_vuln("DEBIAN-CVE-2025-1", "1.0")) == "Details of DEBIAN-CVE-2025-1"

    def test_summary_drops_kernel_boilerplate(self) -> None:
        details = "In the Linux kernel, the following vulnerability has been resolved:\n\nnet: fix use-after-free\n"
        assert osv.summary({"details": details}) == "net: fix use-after-free"

    def test_severity_falls_back_to_declared_value(self) -> None:
        assert osv.severity({"database_specific": {"severity": "HIGH"}}) == "high"
        assert osv.severity({}) is None


# ── Package scan ─────────────────────────────────────────────────────────────

def _osv_transport(vulns_by_package: dict[str, list[list[dict]]], calls: list[str]) -> httpx.MockTransport:
    """vulns_by_package maps a package name to its result pages."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path.endswith("/querybatch"):
            calls.append("batch")
            results = [
                {"vulns": [{"id": "x"}]} if vulns_by_package.get(q["package"]["name"]) else {}
                for q in body["queries"]
            ]
            return httpx.Response(200, json={"results": results})

        name = body["package"]["name"]
        calls.append(name)
        pages = vulns_by_package[name]
        index = int(body.get("page_token", 0))
        payload: dict = {"vulns": pages[index]}
        if index + 1 < len(pages):
            payload["next_page_token"] = str(index + 1)
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_scan_returns_only_fixable_vulns_most_severe_first() -> None:
    calls: list[str] = []
    transport = _osv_transport(
        {
            "apache2": [[
                _vuln("DEBIAN-CVE-2025-1", "2.4.66-1~deb12u1", "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N"),
                _vuln("DEBIAN-CVE-2025-2", None, "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"),
            ]],
            "openssh": [
                [_vuln("DEBIAN-CVE-2026-3", "1:9.2p1-2+deb12u9")],
                [_vuln("DEBIAN-CVE-2026-4", "1:9.2p1-2+deb12u10", "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")],
            ],
        },
        calls,
    )
    packages = [
        {"name": "apache2", "version": "2.4.65-1~deb12u1"},
        {"name": "openssh", "version": "1:9.2p1-2+deb12u7"},
        {"name": "bash", "version": "5.2.15-2"},
        {"name": "", "version": "1.0"},
    ]

    async with httpx.AsyncClient(transport=transport) as client:
        found = await scan_packages(client, ECOSYSTEM, packages)

    assert [v["cve_id"] for v in found] == ["CVE-2026-4", "CVE-2025-1", "CVE-2026-3"]
    assert [v["severity"] for v in found] == ["critical", "high", None]
    assert found[0] == {
        "runtime": "openssh",
        "version": "1:9.2p1-2+deb12u7",
        "cve_id": "CVE-2026-4",
        "severity": "critical",
        "summary": "Details of DEBIAN-CVE-2026-4",
        "fixed_version": "1:9.2p1-2+deb12u10",
        "published_at": "2026-01-01T00:00:00Z",
    }
    # bash has no advisories, so it never costs a detailed query.
    assert "bash" not in calls
    assert calls.count("openssh") == 2


@pytest.mark.asyncio
async def test_scan_caps_entries_per_package_keeping_the_most_severe(monkeypatch) -> None:
    monkeypatch.setattr(package_vulns, "_MAX_VULNS_PER_PACKAGE", 2)
    transport = _osv_transport(
        {
            "linux": [[
                _vuln("DEBIAN-CVE-2026-1", "6.1.187-1"),
                _vuln("DEBIAN-CVE-2026-2", "6.1.187-1", "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"),
                _vuln("DEBIAN-CVE-2026-3", "6.1.187-1", "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N"),
            ]],
        },
        [],
    )

    async with httpx.AsyncClient(transport=transport) as client:
        found = await scan_packages(client, ECOSYSTEM, [{"name": "linux", "version": "6.1.158-1"}])

    assert [v["cve_id"] for v in found] == ["CVE-2026-2", "CVE-2026-3"]


@pytest.mark.asyncio
async def test_scan_without_affected_packages_makes_no_detailed_query() -> None:
    calls: list[str] = []
    async with httpx.AsyncClient(transport=_osv_transport({}, calls)) as client:
        found = await scan_packages(client, ECOSYSTEM, [{"name": "bash", "version": "5.2.15-2"}])

    assert found == []
    assert calls == ["batch"]


@pytest.mark.asyncio
async def test_failed_package_query_does_not_abort_the_scan() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/querybatch"):
            return httpx.Response(200, json={"results": [{"vulns": [{"id": "x"}]}]})
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        found = await scan_packages(client, ECOSYSTEM, [{"name": "apache2", "version": "2.4.65-1~deb12u1"}])

    assert found == []
