"""Roles and what each one may do: the one matrix the API enforces and the dashboard reads
(GET /auth/me returns the caller's permissions).

Not here on purpose: a personal nickname for a server. It is a preference of the account,
not configuration, so every role sets its own (tests/test_roles.py names that exception)."""
from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class Permission(StrEnum):
    VIEW = "view"                    # every dashboard screen
    MANAGE_ALERTS = "alerts.manage"  # rules, channels, sending a test, silences, maintenance
    MANAGE_SERVERS = "servers.manage"  # groups and the shared label of a server
    RECORD_EVENTS = "events.create"  # deploy and maintenance markers on the charts
    RUN_ANALYSIS = "analysis.run"    # starting a correlation run
    MANAGE_AGENTS = "agents.manage"  # registering and removing agents
    MANAGE_USERS = "users.manage"
    VIEW_AUDIT = "audit.view"


_VIEWER = frozenset({Permission.VIEW})
_OPERATOR = _VIEWER | {Permission.MANAGE_ALERTS, Permission.RECORD_EVENTS, Permission.RUN_ANALYSIS}
_ADMIN = frozenset(Permission)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: _VIEWER,
    Role.OPERATOR: _OPERATOR,
    Role.ADMIN: _ADMIN,
}


def permissions_of(role: str) -> frozenset[Permission]:
    """An unknown role (the database forbids one) gets nothing."""
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return frozenset()


def allows(role: str, permission: Permission) -> bool:
    return permission in permissions_of(role)
