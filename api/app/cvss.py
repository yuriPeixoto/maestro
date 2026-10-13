"""CVSS v3.x base score, computed from the vector string.

OSV records carry the vector (``CVSS:3.1/AV:N/AC:L/...``), not the number.
Formula: https://www.first.org/cvss/v3.1/specification-document (section 7).
"""
from __future__ import annotations

import math

_ATTACK_VECTOR = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}
_ATTACK_COMPLEXITY = {"L": 0.77, "H": 0.44}
_PRIVILEGES_UNCHANGED = {"N": 0.85, "L": 0.62, "H": 0.27}
_PRIVILEGES_CHANGED = {"N": 0.85, "L": 0.68, "H": 0.5}
_USER_INTERACTION = {"N": 0.85, "R": 0.62}
_IMPACT = {"H": 0.56, "L": 0.22, "N": 0.0}

_CRITICAL_MIN = 9.0
_HIGH_MIN = 7.0
_MEDIUM_MIN = 4.0


def base_score(vector: str) -> float | None:
    """Return the base score for a CVSS v3.0/v3.1 vector, or None if it is not one."""
    if not vector.upper().startswith("CVSS:3"):
        return None

    metrics = dict(part.split(":", 1) for part in vector.split("/")[1:] if ":" in part)
    try:
        scope_changed = metrics["S"] == "C"
        privileges = _PRIVILEGES_CHANGED if scope_changed else _PRIVILEGES_UNCHANGED
        exploitability = (
            8.22
            * _ATTACK_VECTOR[metrics["AV"]]
            * _ATTACK_COMPLEXITY[metrics["AC"]]
            * privileges[metrics["PR"]]
            * _USER_INTERACTION[metrics["UI"]]
        )
        iss = 1 - (1 - _IMPACT[metrics["C"]]) * (1 - _IMPACT[metrics["I"]]) * (1 - _IMPACT[metrics["A"]])
    except KeyError:
        return None

    if scope_changed:
        impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15
    else:
        impact = 6.42 * iss

    if impact <= 0:
        return 0.0
    if scope_changed:
        return _roundup(min(1.08 * (impact + exploitability), 10))
    return _roundup(min(impact + exploitability, 10))


def severity_label(score: float) -> str:
    if score >= _CRITICAL_MIN:
        return "critical"
    if score >= _HIGH_MIN:
        return "high"
    if score >= _MEDIUM_MIN:
        return "medium"
    return "low"


def _roundup(value: float) -> float:
    """Round up to one decimal, as defined by the spec (avoids float artefacts)."""
    scaled = round(value * 100_000)
    if scaled % 10_000 == 0:
        return scaled / 100_000
    return (math.floor(scaled / 10_000) + 1) / 10
