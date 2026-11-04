"""M1.4 Phase A (M1.3 rows #16 and #19): one store per request, closed on success and on error; no route opens a
project store by hand; a project address may not carry a user name or password."""
from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentqa.api import create_app
from agentqa.api.auth import hash_password
from agentqa.api.settings import Settings
from agentqa.orchestrator import NotFound, projects

API = Path(__file__).resolve().parent.parent / "agentqa" / "api"
OWNER, PASSWORD = "owner@example.com", "correct horse battery staple"
CSRF = {"X-Requested-With": "AgentQA"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    projects.create_demo()
    return tmp_path


def _closed(store) -> bool:
    try:
        store.conn.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return True
    return False


def test_the_store_is_closed_when_the_block_ends(home):
    with projects.project_store("demo") as (p, s):
        assert p.root.name == "demo" and s.scalar("SELECT 1") == 1
    assert _closed(s)


def test_the_store_is_closed_when_the_block_raises(home):
    with pytest.raises(RuntimeError):
        with projects.project_store("demo") as (_, s):
            raise RuntimeError("boom")
    assert _closed(s)


def test_an_unknown_project_opens_no_store(home):
    with pytest.raises(NotFound):
        with projects.project_store("nope"):
            pass


def _calls(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            names.add(func.id if isinstance(func, ast.Name) else getattr(func, "attr", ""))
    return names


def test_no_route_opens_a_project_store_by_hand():
    for f in sorted(API.glob("routes_*.py")):
        used = _calls(ast.parse(f.read_text(encoding="utf-8")))
        assert not used & {"open_project", "open_or_404", "Store"}, f.name


@pytest.fixture
def client(home):
    settings = Settings(owner_email=OWNER, owner_password_hash=hash_password(PASSWORD), secret_key="s" * 40)
    c = TestClient(create_app(settings, legacy=True), follow_redirects=False)
    c.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD}, headers=CSRF)
    return c


def test_every_store_a_project_request_opens_is_closed(client, monkeypatch):
    """Each store records its own close() (a connection made in a server thread cannot be queried from this one)."""
    opened = []

    class Tracked(projects.Store):
        def __init__(self, path):
            super().__init__(path)
            self.was_closed = False
            opened.append(self)

        def close(self):
            self.was_closed = True
            super().close()

    projects.Store(projects.find_project("demo").db_path).close()     # the database exists, so the list reads it
    monkeypatch.setattr(projects, "Store", Tracked)
    for url in ("/api/v1/projects", "/api/v1/projects/demo", "/api/v1/projects/demo/runs",
                "/api/v1/projects/demo/requirements", "/api/v1/projects/demo/live/sessions"):
        before = len(opened)
        assert client.get(url).status_code == 200, url
        assert len(opened) > before, url
    assert all(s.was_closed for s in opened)


@pytest.mark.parametrize("url", ["https://user:secret@uat.example.gov.in", "http://admin@uat.example.gov.in/x"])
def test_an_address_with_a_user_name_or_password_is_refused_by_the_api(client, url):
    r = client.post("/api/v1/projects", json={"name": "UR Portal", "url": url}, headers=CSRF)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation"
    assert "secret" not in r.text
    assert not (projects.projects_dir() / "ur-portal").exists()


def test_an_address_with_a_user_name_or_password_is_refused_by_the_old_form(client):
    r = client.post("/new", data={"name": "UR Portal", "url": "https://user:secret@uat.example.gov.in"})
    assert r.status_code == 422 and "secret" not in r.text
    assert not (projects.projects_dir() / "ur-portal").exists()


def test_create_project_refuses_a_user_name_in_the_address(home):
    with pytest.raises(ValueError, match="user name or password"):
        projects.create_project("UR Portal", "https://user:secret@uat.example.gov.in")


def test_an_at_sign_after_the_host_is_still_a_normal_address(client):
    r = client.post("/api/v1/projects", json={"name": "UR Portal", "url": "https://uat.example.gov.in/@home"}, headers=CSRF)
    assert r.status_code == 201


def test_init_project_refuses_a_user_name_in_the_address(tmp_path):
    from agentqa.config import init_project
    with pytest.raises(ValueError, match="user name or password"):
        init_project(tmp_path / "x", "X", "https://admin:pw@uat.example.gov.in")
    assert not (tmp_path / "x" / "project.yaml").exists()


def test_the_old_add_application_form_refuses_a_user_name_too(client):
    r = client.post("/p/demo/testdata/app", data={"id": "dept", "base_url": "https://admin:secret@dept.example.gov.in"})
    assert r.status_code == 422 and "secret" not in r.text
    assert "secret" not in projects.find_project("demo").config_path.read_text(encoding="utf-8")


def test_an_address_saved_with_a_password_before_is_never_shown(client):
    p = projects.find_project("demo")
    p.config_path.write_text(p.config_path.read_text(encoding="utf-8").replace(
        p.cfg["base_url"], "http://admin:secret@127.0.0.1:8800", 1), encoding="utf-8")
    for url in ("/api/v1/projects", "/api/v1/projects/demo"):
        r = client.get(url)
        assert r.status_code == 200 and "secret" not in r.text and "127.0.0.1:8800" in r.text
