"""Where a rule, a channel or a silence applies, and which rule wins on a server.

A place is every server (`global`), a group, or one server. For each metric and
severity a server is judged by the most specific rule that covers it: its own, else
its group's, else the global one. A winning rule that is switched off (`enabled`
false) silences the metric there. Pure functions: nothing here touches the database.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

SCOPE_GLOBAL = "global"
SCOPE_GROUP = "group"
SCOPE_SERVER = "server"
SCOPES = (SCOPE_GLOBAL, SCOPE_GROUP, SCOPE_SERVER)

_SPECIFICITY = {SCOPE_GLOBAL: 0, SCOPE_GROUP: 1, SCOPE_SERVER: 2}


@dataclass(frozen=True)
class Place:
    scope: str
    server_id: str | None = None
    group_id: int | None = None

    def __post_init__(self) -> None:
        valid = {
            SCOPE_GLOBAL: self.server_id is None and self.group_id is None,
            SCOPE_GROUP: self.server_id is None and self.group_id is not None,
            SCOPE_SERVER: self.server_id is not None and self.group_id is None,
        }
        if not valid.get(self.scope, False):
            raise ValueError(f"Invalid place: scope={self.scope!r} server_id={self.server_id!r} group_id={self.group_id!r}")

    def covers(self, server_id: str, group_id: int | None) -> bool:
        if self.scope == SCOPE_GLOBAL:
            return True
        if self.scope == SCOPE_GROUP:
            return group_id is not None and self.group_id == group_id
        return self.server_id == server_id


class _Rule(Protocol):
    metric_name: str
    severity: str
    enabled: bool

    @property
    def place(self) -> Place: ...


def resolve[R: _Rule](rules: list[R], server_id: str, group_id: int | None) -> list[tuple[R, list[R]]]:
    """Per metric and severity, the rule that wins on this server and the ones it overrides
    (most specific first), in the order the winners first appear in `rules`."""
    covering: dict[tuple[str, str], list[R]] = {}
    for rule in rules:
        if rule.place.covers(server_id, group_id):
            covering.setdefault((rule.metric_name, rule.severity), []).append(rule)
    resolved = []
    for candidates in covering.values():
        ranked = sorted(candidates, key=lambda r: _SPECIFICITY[r.place.scope], reverse=True)
        resolved.append((ranked[0], ranked[1:]))
    return resolved


def effective[R: _Rule](rules: list[R], server_id: str, group_id: int | None) -> list[R]:
    """The rules judged on this server: each winner that is switched on."""
    return [winner for winner, _overridden in resolve(rules, server_id, group_id) if winner.enabled]
