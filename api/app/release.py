"""Maestro's version, and what changed for the people who use the dashboard.

The version lives in the repository's VERSION file; pyproject.toml repeats it and
is what ships with the API, so this module reads it from there. A test keeps both
(and frontend/package.json) in step.

Release notes are short, written for the dashboard's users, in every language the
interface speaks (`release_notes.json`). The technical history is CHANGELOG.md.
"""
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
_NOTES = Path(__file__).with_name("release_notes.json")


def _read_version() -> str:
    with _PYPROJECT.open("rb") as file:
        return tomllib.load(file)["project"]["version"]


VERSION = _read_version()


@dataclass(frozen=True)
class Release:
    version: str
    date: str                     # "YYYY-MM-DD"
    notes: dict[str, list[str]]   # language -> lines


def parse_version(version: str) -> tuple[int, ...]:
    """"0.1.0" -> (0, 1, 0); anything after a hyphen (pre-release) is ignored."""
    return tuple(int(part) for part in version.split("-")[0].split("."))


def releases() -> list[Release]:
    """Every release with notes, newest first."""
    data = json.loads(_NOTES.read_text(encoding="utf-8"))
    entries = [Release(e["version"], e["date"], e["notes"]) for e in data]
    return sorted(entries, key=lambda r: parse_version(r.version), reverse=True)


def unseen(last_seen: str | None) -> list[Release]:
    """Releases newer than `last_seen`; all of them when nothing was seen yet."""
    if not last_seen:
        return releases()
    seen = parse_version(last_seen)
    return [r for r in releases() if parse_version(r.version) > seen]
