"""M1.3 (FR-LIVE-8): a Viewer watches everything and changes nothing. One rule in the request guard refuses every
write (POST / PUT / PATCH / DELETE) from a role that may not write, on the API and on the old dashboard alike; sign-in
and sign-out stay open. Viewer accounts arrive with team logins (M2.1); here the Viewer's pass is made by the test."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentqa.api import create_app
from agentqa.api.auth import COOKIE, WRITE_ROLES, User, hash_password
from agentqa.api.settings import Settings

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "recordings" / "cli-fixture-pipeline"
OWNER, PASSWORD = "owner@example.com", "correct horse battery staple"
CSRF = {"X-Requested-With": "AgentQA"}
SAFE = {"GET", "HEAD", "OPTIONS"}
OPEN_WRITES = {"/api/v1/auth/login", "/api/v1/auth/logout"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    settings = Settings(owner_email=OWNER, owner_password_hash=hash_password(PASSWORD), secret_key="s" * 40)
    application = create_app(settings, legacy=True)
    owner = TestClient(application, follow_redirects=False)
    owner.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD}, headers=CSRF)
    owner.post("/api/v1/projects/demo", headers=CSRF)
    from agentqa.orchestrator.projects import find_project
    p = find_project("demo")
    shutil.copytree(FIXTURE, p.state / "live" / "cli-fixture-pipeline")
    return application


def client_as(application, role: str) -> TestClient:
    c = TestClient(application, follow_redirects=False)
    c.cookies.set(COOKIE, application.state.sessions.issue(User(email=f"{role or 'nobody'}@example.com", role=role)))
    return c


def write_routes(application) -> list[tuple[str, str]]:
    """Every (method, path) the API publishes that changes something, with its path parameters filled in."""
    out = []
    for path, operations in application.openapi()["paths"].items():
        for method in sorted(m.upper() for m in operations):
            if method in SAFE or path in OPEN_WRITES:
                continue
            out.append((method, re.sub(r"\{(\w+)(:\w+)?\}", lambda m: "1" if m.group(1).endswith("id") else "demo", path)))
    return out


def test_the_roles_that_may_write_are_owner_and_tester():
    assert WRITE_ROLES == frozenset({"owner", "tester"})


def test_a_viewer_may_read_every_live_endpoint(app):
    viewer = client_as(app, "viewer")
    base = "/api/v1/projects/demo/live"
    assert viewer.get("/api/v1/auth/me").json()["data"]["role"] == "viewer"
    assert viewer.get(f"{base}/sessions").status_code == 200
    assert viewer.get(f"{base}/board").status_code == 200
    assert viewer.get(f"{base}/cli-fixture-pipeline/events").status_code == 200
    shot = sorted((FIXTURE / "shots").iterdir())[0].name
    assert viewer.get(f"{base}/cli-fixture-pipeline/shots/{shot}").status_code == 200
    with viewer.stream("GET", f"{base}/cli-fixture-pipeline/stream") as r:
        assert r.status_code == 200 and "event: end" in "".join(r.iter_text())


def test_every_write_route_refuses_a_viewer(app):
    viewer = client_as(app, "viewer")
    routes = write_routes(app)
    assert len(routes) >= 24          # …, AI keys, policy, and the gates' 9 decisions (M1.4 A); Phase C takes it past 30
    for method, path in routes:
        r = viewer.request(method, path, headers=CSRF, json={})
        assert r.status_code == 403 and r.json()["error"]["code"] == "read_only", (method, path, r.status_code)


GATE_READS = ("questions", "plan", "plan/cases", "plan/testcases.xlsx", "defects", "defects/export.csv",
              "defects/zoho.csv", "requirements", "requirements/rtm.xlsx", "changes", "gates")


@pytest.mark.parametrize("path", GATE_READS)
def test_a_viewer_reads_every_gate_page_and_download(app, path):
    assert client_as(app, "viewer").get(f"/api/v1/projects/demo/{path}").status_code == 200


def test_the_old_dashboards_forms_refuse_a_viewer_too(app):
    viewer = client_as(app, "viewer")
    r = viewer.post("/new", data={"name": "x", "url": "https://x.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "read_only"
    assert viewer.get("/").status_code == 200                 # reading the old dashboard is fine


@pytest.mark.parametrize("role", ["", "admin", "Viewer", "guest"])
def test_an_unknown_role_counts_as_read_only(app, role):
    r = client_as(app, role).post("/api/v1/projects", json={"name": "X", "url": "https://x.example"}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"]["code"] == "read_only"


def test_owners_and_testers_still_write(app):
    for role in ("owner", "tester"):
        r = client_as(app, role).post("/api/v1/projects", json={"name": f"P {role}", "url": "https://x.example"},
                                      headers=CSRF)
        assert r.status_code == 201, role


def test_signing_in_and_out_stay_open_to_everyone(app):
    viewer = client_as(app, "viewer")
    assert viewer.post("/api/v1/auth/logout", headers=CSRF).status_code == 200
    r = client_as(app, "viewer").post("/api/v1/auth/login", json={"email": OWNER, "password": "wrong"}, headers=CSRF)
    assert r.status_code == 401                               # refused for the password, not for the role


def test_signed_out_writes_still_get_401_not_403(app):
    r = TestClient(app).post("/api/v1/projects", json={"name": "X", "url": "https://x.example"}, headers=CSRF)
    assert r.status_code == 401
