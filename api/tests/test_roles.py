"""
Roles: every write route declares a permission, and each role gets exactly what the
matrix in app.permissions says on the sensitive routes.

The matrix tests run against the real app's routes (app.main) without its lifespan:
an allowed call may fail further in (no ClickHouse here), so they only check that
the role check lets it through (anything but 403) or stops it (403).
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app as real_app
from app.permissions import ROLE_PERMISSIONS, Permission, Role, allows, permissions_of
from tests.conftest import act_as

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# The account's own endpoints: any logged-in role (and login itself).
_OWN_ACCOUNT_ROUTES = {
    "/auth/login", "/auth/logout", "/auth/me", "/auth/me/release-seen", "/auth/change-password",
}
# Personal preferences, not configuration: every role manages its own, and they change
# only that account's screens (app.permissions says why). Each one is tested below.
_PERSONAL_PREFERENCE_ROUTES = {
    "/servers/{server_id}/nickname",
}

_RULE = {"metric_name": "cpu_usage_percent", "operator": ">=", "threshold": 90, "severity": "critical"}
_UUID = "00000000-0000-0000-0000-000000000001"

# (method, path, body, permission it needs)
SENSITIVE_ROUTES = [
    ("POST", "/alerts/web-1/rules", _RULE, Permission.MANAGE_ALERTS),
    ("DELETE", f"/alerts/web-1/rules/{_UUID}", None, Permission.MANAGE_ALERTS),
    ("POST", "/alerts/web-1/channels", {"channel_type": "telegram"}, Permission.MANAGE_ALERTS),
    ("DELETE", f"/alerts/web-1/channels/{_UUID}", None, Permission.MANAGE_ALERTS),
    ("POST", f"/alerts/web-1/channels/{_UUID}/test", None, Permission.MANAGE_ALERTS),
    ("POST", "/events/web-1", {"event_type": "deploy", "label": "x"}, Permission.RECORD_EVENTS),
    ("POST", "/analysis/web-1/correlations/run", None, Permission.RUN_ANALYSIS),
    ("DELETE", "/agents/web-1", None, Permission.MANAGE_AGENTS),
    ("GET", "/users", None, Permission.MANAGE_USERS),
    ("POST", "/users", {"username": "x", "email": "x@example.com"}, Permission.MANAGE_USERS),
    ("PATCH", "/users/2", {"role": "viewer"}, Permission.MANAGE_USERS),
    ("POST", "/users/2/deactivate", None, Permission.MANAGE_USERS),
    ("POST", "/users/2/reactivate", None, Permission.MANAGE_USERS),
    ("POST", "/users/2/temporary-password", None, Permission.MANAGE_USERS),
    ("GET", "/audit", None, Permission.VIEW_AUDIT),
    ("POST", "/alerts/rules", {**_RULE, "scope": "global"}, Permission.MANAGE_ALERTS),
    ("PATCH", f"/alerts/rules/{_UUID}", {"threshold": 95}, Permission.MANAGE_ALERTS),
    ("DELETE", f"/alerts/rules/{_UUID}", None, Permission.MANAGE_ALERTS),
    ("POST", "/alerts/channels", {"scope": "global", "channel_type": "telegram"}, Permission.MANAGE_ALERTS),
    ("DELETE", f"/alerts/channels/{_UUID}", None, Permission.MANAGE_ALERTS),
    ("POST", f"/alerts/channels/{_UUID}/test", None, Permission.MANAGE_ALERTS),
    ("POST", "/alerts/silences", {"scope": "global", "duration_minutes": 30, "reason": "x"}, Permission.MANAGE_ALERTS),
    ("POST", f"/alerts/silences/{_UUID}/end", None, Permission.MANAGE_ALERTS),
    ("POST", "/alerts/maintenance", {"server_id": "web-1", "reason": "x"}, Permission.MANAGE_ALERTS),
    ("DELETE", f"/alerts/maintenance/{_UUID}", None, Permission.MANAGE_ALERTS),
    ("POST", f"/alerts/web-1/rules/{_UUID}/acknowledge", None, Permission.ACKNOWLEDGE_ALERTS),
    ("PATCH", "/servers/web-1", {"label": "Web"}, Permission.MANAGE_SERVERS),
    ("POST", "/server-groups", {"name": "web"}, Permission.MANAGE_SERVERS),
    ("PATCH", "/server-groups/2", {"name": "web"}, Permission.MANAGE_SERVERS),
    ("DELETE", "/server-groups/2", None, Permission.MANAGE_SERVERS),
]


def _write_routes() -> list[tuple[str, str]]:
    """Every write route of the real app, from its OpenAPI document (the public contract),
    with path parameters filled in."""
    routes = []
    for template, operations in real_app.openapi()["paths"].items():
        if template in _OWN_ACCOUNT_ROUTES | _PERSONAL_PREFERENCE_ROUTES:
            continue
        path = re.sub(r"\{[^}]+\}", _UUID, template)
        routes += [(method.upper(), path) for method in operations if method.upper() in _WRITE_METHODS]
    return routes


def test_the_write_routes_are_found():
    # Guards the guard: an empty list would make the next test pass without checking anything.
    assert len(_write_routes()) >= 14


def test_a_viewer_can_change_nothing(as_role):
    """A viewer has only VIEW, so a write route that answers anything but 403 to it
    was added without app.auth.require."""
    client = as_role(Role.VIEWER)
    let_through = [
        f"{method} {path} -> {response.status_code}"
        for method, path in _write_routes()
        if (response := client.request(method, path, json={})).status_code != 403
    ]
    assert let_through == []


def test_the_sensitive_routes_listed_here_exist():
    templates = {
        (method.upper(), re.sub(r"\{[^}]+\}", "*", template))
        for template, operations in real_app.openapi()["paths"].items() for method in operations
    }
    for method, path, _body, _permission in SENSITIVE_ROUTES:
        shape = re.sub(r"/(web-1|2|" + _UUID + r")(?=/|$)", "/*", path)
        assert (method, shape) in templates, (method, path)


def test_roles_grow_from_viewer_to_admin():
    assert ROLE_PERMISSIONS[Role.VIEWER] < ROLE_PERMISSIONS[Role.OPERATOR] < ROLE_PERMISSIONS[Role.ADMIN]
    assert ROLE_PERMISSIONS[Role.ADMIN] == frozenset(Permission)
    assert permissions_of("superuser") == frozenset()


@pytest.fixture
def as_role():
    client = TestClient(real_app, raise_server_exceptions=False)

    def use(role: Role) -> TestClient:
        act_as(real_app, role=role.value, user_id=1)
        return client

    yield use
    real_app.dependency_overrides.clear()


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize(("method", "path", "body", "permission"), SENSITIVE_ROUTES)
def test_each_role_on_each_sensitive_route(as_role, role, method, path, body, permission):
    response = as_role(role).request(method, path, json=body)

    if allows(role, permission):
        assert response.status_code != 403, response.text
    else:
        assert response.status_code == 403
        assert response.json()["detail"] == "Not allowed for your role"


def test_the_personal_preference_routes_exist():
    assert _PERSONAL_PREFERENCE_ROUTES <= set(real_app.openapi()["paths"])


@pytest.mark.parametrize("role", list(Role))
def test_every_role_manages_its_own_nickname(as_role, role):
    """The named exception: not even a viewer gets a 403 here (the database part of the
    behaviour, one account not seeing another's, is in test_server_names.py)."""
    client = as_role(role)

    assert client.put("/servers/web-1/nickname", json={"nickname": "Mine"}).status_code != 403
    assert client.delete("/servers/web-1/nickname").status_code != 403


@pytest.mark.parametrize("role", list(Role))
def test_every_role_reads_the_dashboard(as_role, role):
    # /meta answers without ClickHouse; any read route needs only a login.
    assert as_role(role).get("/meta").status_code != 403
