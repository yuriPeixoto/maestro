"""Helpers for reading OSV.dev vulnerability records (https://ossf.github.io/osv-schema/)."""
from __future__ import annotations

from app import cvss

OSV_QUERY_URL = "https://api.osv.dev/v1/query"
OSV_QUERYBATCH_URL = "https://api.osv.dev/v1/querybatch"

_SUMMARY_MAX_CHARS = 200
# Every kernel CVE description opens with this sentence; the actual subject follows it.
_KERNEL_BOILERPLATE = "In the Linux kernel, the following vulnerability has been resolved:"


def cve_id(vuln: dict) -> str:
    """Prefer the CVE identifier; distribution records list it under ``upstream``."""
    for field in ("aliases", "upstream"):
        for identifier in vuln.get(field) or []:
            if identifier.startswith("CVE-"):
                return identifier
    return vuln.get("id", "UNKNOWN")


def score(vuln: dict) -> float | None:
    for entry in vuln.get("severity") or []:
        if entry.get("type") != "CVSS_V3":
            continue
        value = cvss.base_score(entry.get("score") or "")
        if value is not None:
            return value
    return None


def severity(vuln: dict) -> str | None:
    value = score(vuln)
    if value is not None:
        return cvss.severity_label(value)
    declared = (vuln.get("database_specific") or {}).get("severity")
    return declared.lower() if isinstance(declared, str) else None


def fixed_version(vuln: dict, ecosystem: str | None = None) -> str | None:
    """First fixed version on record, optionally restricted to one ecosystem."""
    for affected in vuln.get("affected") or []:
        if ecosystem and (affected.get("package") or {}).get("ecosystem") != ecosystem:
            continue
        for version_range in affected.get("ranges") or []:
            for event in version_range.get("events") or []:
                if event.get("fixed"):
                    return event["fixed"]
    return None


def summary(vuln: dict) -> str:
    text = vuln.get("summary") or vuln.get("details") or vuln.get("id") or "No summary"
    text = text.strip().removeprefix(_KERNEL_BOILERPLATE).strip()
    first_line = text.splitlines()[0] if text else "No summary"
    if len(first_line) <= _SUMMARY_MAX_CHARS:
        return first_line
    return first_line[: _SUMMARY_MAX_CHARS - 1].rstrip() + "…"
