"""
One version for the whole project, release notes for the dashboard's users, and
"what's new" shown once per account.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update

from app import auth_db, db, login_throttle, release
from app.about import router as about_router
from app.auth import router as auth_router
from app.config import settings
from app.models import User

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "a-good-password"


class TestOneVersion:
    def test_every_manifest_carries_the_version_file(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))

        assert release.VERSION == version
        assert package["version"] == version

    def test_the_newest_notes_are_for_the_current_version_in_every_language(self):
        newest = release.releases()[0]

        assert newest.version == release.VERSION
        assert set(newest.notes) == {"pt-BR", "en"}
        assert len(newest.notes["pt-BR"]) == len(newest.notes["en"])


class TestUnseen:
    def test_nothing_seen_shows_every_release(self):
        assert [r.version for r in release.unseen(None)] == [r.version for r in release.releases()]

    def test_the_current_version_leaves_nothing_new(self):
        assert release.unseen(release.VERSION) == []

    def test_versions_compare_as_numbers(self):
        assert release.parse_version("0.10.0") > release.parse_version("0.9.1")
        assert release.parse_version("0.1.0-dev") == (0, 1, 0)


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password_hash", "")
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-" + "0" * 32)
    login_throttle._failures.clear()


def _login(client: TestClient, username: str) -> dict:
    token = client.post("/auth/login", json={"username": username, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(postgres) -> TestClient:
    app = FastAPI()
    app.include_router(auth_router)
    return TestClient(app)


class TestReleaseSeen:
    async def _create(self, username: str) -> None:
        await auth_db.create_user(username, f"{username}@example.com", PASSWORD)

    @pytest.mark.asyncio
    async def test_a_new_account_starts_at_the_current_version(self, client):
        await self._create("ana")

        assert client.get("/auth/me", headers=_login(client, "ana")).json()["last_seen_version"] == release.VERSION

    @pytest.mark.asyncio
    async def test_an_account_from_before_the_notes_sees_them_once(self, client):
        await self._create("bia")
        async with db.session() as s:
            await s.execute(update(User).values(last_seen_version=None))
        headers = _login(client, "bia")

        assert client.get("/auth/me", headers=headers).json()["last_seen_version"] is None
        assert client.post("/auth/me/release-seen", json={"version": release.VERSION}, headers=headers).status_code == 204
        assert client.get("/auth/me", headers=headers).json()["last_seen_version"] == release.VERSION

    @pytest.mark.asyncio
    async def test_a_version_newer_than_the_running_one_is_refused(self, client):
        await self._create("caio")

        resp = client.post("/auth/me/release-seen", json={"version": "99.0.0"}, headers=_login(client, "caio"))

        assert resp.status_code == 422


class _Redis:
    async def hgetall(self, _key):
        return {
            "web-2": json.dumps({"agent_version": "0.0.9", "last_seen": "2026-11-05T12:00:00+00:00"}),
            "web-1": json.dumps({"agent_version": release.VERSION, "last_seen": "2026-11-05T12:00:01+00:00"}),
            "broken": "not json",
        }


class _ClickHouse:
    async def query(self, _sql):
        class _Result:
            result_rows = [("25.5.2.47",)]
        return _Result()


def test_about_lists_versions_database_and_agents():
    app = FastAPI()
    app.include_router(about_router)
    app.state.vuln_redis = _Redis()
    app.state.ch_client = _ClickHouse()

    body = TestClient(app).get("/about").json()

    assert body["version"] == release.VERSION
    assert body["clickhouse_version"] == "25.5.2.47"
    assert [(a["server_id"], a["version"]) for a in body["agents"]] == [("web-1", release.VERSION), ("web-2", "0.0.9")]
    assert body["releases"][0]["version"] == release.VERSION
