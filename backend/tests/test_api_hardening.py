"""Findings of the M0.5 security review, each pinned by a test before the fix."""
from __future__ import annotations

import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from agentqa.api import create_app
from agentqa.api.auth import hash_password
from agentqa.api.ratelimit import RateLimiter
from agentqa.api.settings import Settings, load_dotenv
from agentqa.orchestrator import jobs

OWNER, PASSWORD = "owner@example.com", "correct horse battery staple"
CSRF = {"X-Requested-With": "AgentQA"}


def settings(**over) -> Settings:
    return Settings(owner_email=OWNER, owner_password_hash=hash_password(PASSWORD), secret_key="s" * 40, **over)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    return TestClient(create_app(settings()))


def login(c: TestClient):
    return c.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD}, headers=CSRF)


# ---- HIGH-1: the old dashboard mounted at / needs the same sign-in -------------------------------

def test_the_legacy_dashboard_is_behind_the_same_sign_in(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    c = TestClient(create_app(settings(), legacy=True), follow_redirects=False)

    anonymous = c.get("/")
    assert anonymous.status_code == 303 and anonymous.headers["location"] == "/app/sign-in"
    assert c.post("/new", data={"name": "x", "url": "https://x.example"}).status_code == 401

    login(c)
    assert c.get("/").status_code == 200


# ---- HIGH-2: jobs must not inherit the signing secret or the password hash ----------------------

def test_child_env_never_carries_the_api_secrets(monkeypatch):
    monkeypatch.setenv("AGENTQA_SECRET_KEY", "super-secret")
    monkeypatch.setenv("AGENTQA_OWNER_PASSWORD_HASH", "$argon2id$hash")
    monkeypatch.setenv("AGENTQA_OWNER_EMAIL", OWNER)
    monkeypatch.setenv("AGENTQA_PROJECTS", "keep-me")

    env = jobs.child_env({"AGENTQA_LIVE_DIR": "x"})

    assert "AGENTQA_SECRET_KEY" not in env and "AGENTQA_OWNER_PASSWORD_HASH" not in env and "AGENTQA_OWNER_EMAIL" not in env
    assert env["AGENTQA_PROJECTS"] == "keep-me" and env["AGENTQA_LIVE_DIR"] == "x"


def test_load_dotenv_returns_values_without_touching_the_process_environment(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('AGENTQA_SECRET_KEY="quoted=value"\n# comment\nAGENTQA_OWNER_EMAIL=o@x.io\n', encoding="utf-8")
    monkeypatch.delenv("AGENTQA_SECRET_KEY", raising=False)

    values = load_dotenv(f)

    assert values["AGENTQA_SECRET_KEY"] == "quoted=value" and values["AGENTQA_OWNER_EMAIL"] == "o@x.io"
    assert "AGENTQA_SECRET_KEY" not in os.environ


# ---- MEDIUM-3: a wrong email must cost as much as a wrong password ------------------------------

def test_wrong_email_and_wrong_password_take_similar_time(client):
    def timed(email):
        start = time.perf_counter()
        client.post("/api/v1/auth/login", json={"email": email, "password": "nope"}, headers=CSRF)
        return time.perf_counter() - start

    timed(OWNER)                                             # warm up argon2 once
    wrong_email, wrong_password = timed("nobody@example.com"), timed(OWNER)
    assert wrong_email > 0.3 * wrong_password                # both run the password hash


# ---- MEDIUM-6: logout always clears the cookie, even without a valid session --------------------

def test_logout_works_without_a_session(client):
    r = client.post("/api/v1/auth/logout", headers=CSRF)
    assert r.status_code == 200 and "agentqa_session=" in r.headers.get("set-cookie", "")


# ---- MEDIUM-9: a slug collision with a different application is a conflict ----------------------

def test_a_second_project_with_the_same_slug_but_another_url_is_a_conflict(client):
    login(client)
    assert client.post("/api/v1/projects", json={"name": "UR Portal", "url": "https://a.example"}, headers=CSRF).status_code == 201
    r = client.post("/api/v1/projects", json={"name": "ur_portal", "url": "https://b.example"}, headers=CSRF)
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"


# ---- MEDIUM-10: security headers on the app ---------------------------------------------------

def test_security_headers_are_set(client, tmp_path):
    r = client.get("/api/v1/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_the_app_shell_gets_a_csp_and_is_never_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    c = TestClient(create_app(settings(), frontend_dist=dist))
    r = c.get("/app/projects/demo")
    assert "default-src 'self'" in r.headers["content-security-policy"] and "no-cache" in r.headers["cache-control"]
    assert c.get("/app/assets/missing.js").status_code == 404     # LOW-26: never the shell for a missing asset


# ---- MEDIUM-8: the stream delivers events written just before the run ended --------------------

def test_sse_flushes_events_written_right_before_the_end(client, tmp_path, monkeypatch):
    login(client)
    client.post("/api/v1/projects/demo", headers=CSRF)
    from agentqa.orchestrator import live
    from agentqa.orchestrator.projects import open_project
    p, _ = open_project("demo")
    d = p.state / "live" / "job-1-run"
    d.mkdir(parents=True)
    calls = {"n": 0}
    real = live.read_events

    def late_writer(folder, cursor=""):                       # the job writes its last event after the first empty read
        calls["n"] += 1
        if calls["n"] == 1:
            with (d / "events-main.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": 1, "seq": 1, "w": "main", "agent": "x", "kind": "stage_end", "title": "last"}) + "\n")
            return [], cursor
        return real(folder, cursor)

    monkeypatch.setattr("agentqa.api.routes_live.live.read_events", late_writer)
    with client.stream("GET", "/api/v1/projects/demo/live/job-1-run/stream") as r:
        body = "".join(r.iter_text())
    assert '"last"' in body and body.index('"last"') < body.index("event: end")


# ---- MEDIUM-15: the rate limiter and the dead-job transition get their own tests ----------------

def test_rate_limiter_refills_over_time_and_forgets_idle_clients():
    rl = RateLimiter(per_minute=60, max_clients=2)
    assert all(rl.allow("a") for _ in range(60)) and not rl.allow("a")
    rl._buckets["a"] = (0.0, time.time() - 1.0)             # one second later: one token back
    assert rl.allow("a") and not rl.allow("a")
    rl.allow("b"); rl.allow("c")                              # the cap evicts the oldest client
    assert len(rl._buckets) <= 2


def test_a_run_whose_process_died_is_reported_failed(client, monkeypatch):
    login(client)
    client.post("/api/v1/projects/demo", headers=CSRF)
    from agentqa.orchestrator.projects import open_project
    _, s = open_project("demo")
    job_id = s.insert("jobs", {"stage": "explore", "status": "running", "started_at": "2026-11-03T00:00:00", "pid": 999999999})
    monkeypatch.setattr("agentqa.orchestrator.jobs.pid_alive", lambda pid: False)

    r = client.get(f"/api/v1/projects/demo/runs/{job_id}")
    assert r.json()["data"]["status"] == "failed" and r.json()["data"]["exit_code"] == -1


# ---- MEDIUM-16: a broken project must not leak server paths through the API ---------------------

def test_a_broken_project_does_not_leak_paths(client, tmp_path):
    login(client)
    bad = tmp_path / "projects" / "broken"
    bad.mkdir(parents=True)
    (bad / "project.yaml").write_text("name: [unclosed", encoding="utf-8")
    rows = client.get("/api/v1/projects").json()["data"]
    broken = next(r for r in rows if r["slug"] == "broken")
    assert str(tmp_path) not in json.dumps(broken) and broken["url"] == "configuration error"


# ---- LOW-21: 429 carries Retry-After ---------------------------------------------------------

def test_lockout_tells_the_client_when_to_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    c = TestClient(create_app(settings(login_attempts=1)))
    c.post("/api/v1/auth/login", json={"email": OWNER, "password": "nope"}, headers=CSRF)
    r = c.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD}, headers=CSRF)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
