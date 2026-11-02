"""The built React app is served at /app with a single-page fallback: any /app/... route returns index.html, real
files are served as themselves, and nothing outside the build folder is reachable."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentqa.api import create_app
from agentqa.api.settings import Settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>AgentQA Studio</title><div id=root></div>", encoding="utf-8")
    (dist / "assets" / "index-abc.js").write_text("console.log('app')", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("not for you", encoding="utf-8")
    return TestClient(create_app(Settings(secret_key="s" * 40), frontend_dist=dist))


def test_deep_links_fall_back_to_the_app_shell(client):
    for path in ("/app", "/app/", "/app/projects/demo", "/app/projects/demo/live?session=job-1-pipeline"):
        r = client.get(path)
        assert r.status_code == 200 and "<div id=root>" in r.text, path


def test_real_files_are_served_as_themselves(client):
    r = client.get("/app/assets/index-abc.js")
    assert r.status_code == 200 and "console.log" in r.text


def test_paths_cannot_escape_the_build_folder(client):
    r = client.get("/app/../secret.txt")
    assert "not for you" not in r.text
    r = client.get("/app/%2e%2e/secret.txt")
    assert "not for you" not in r.text


def test_without_a_build_the_app_route_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    c = TestClient(create_app(Settings(secret_key="s" * 40), frontend_dist=tmp_path / "missing"))
    r = c.get("/app/")
    assert r.status_code == 503 and "build" in r.text.lower()
