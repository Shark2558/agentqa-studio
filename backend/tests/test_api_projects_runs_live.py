"""/api/v1 projects, runs and live endpoints against a temporary projects folder; job spawning is faked."""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from agentqa.api import create_app
from agentqa.api.auth import hash_password
from agentqa.api.settings import Settings
from agentqa.orchestrator import jobs

OWNER, PASSWORD = "owner@example.com", "correct horse battery staple"
CSRF = {"X-Requested-With": "AgentQA"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    settings = Settings(owner_email=OWNER, owner_password_hash=hash_password(PASSWORD), secret_key="s" * 40)
    c = TestClient(create_app(settings))
    c.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD}, headers=CSRF)
    return c


@pytest.fixture
def fake_spawn(monkeypatch):
    """Record the job the API would start instead of launching a process; the job row is created for real."""
    started = []

    def spawn(p, s, args, label, headed=False, shots=None):
        if jobs.running(s):
            raise jobs.Busy("A stage is already running for this project.")
        job_id = s.insert("jobs", {"stage": label, "status": "running", "started_at": "2026-11-03T00:00:00",
                                   "log_path": str(p.state / "logs" / "fake.log"), "pid": 999999999})
        started.append((args, label))
        return job_id

    monkeypatch.setattr("agentqa.api.routes_runs.spawn", spawn)
    monkeypatch.setattr("agentqa.orchestrator.jobs.pid_alive", lambda pid: True)
    return started


# ---- projects -------------------------------------------------------------------------------

def test_create_list_and_open_a_project(client):
    r = client.post("/api/v1/projects", json={"name": "UR Portal", "url": "https://uat.example.gov.in"}, headers=CSRF)
    assert r.status_code == 201 and r.json()["data"]["slug"] == "ur-portal"
    assert [p["slug"] for p in client.get("/api/v1/projects").json()["data"]] == ["ur-portal"]
    assert client.get("/api/v1/projects/ur-portal").json()["data"]["url"] == "https://uat.example.gov.in"


def test_a_bad_url_or_empty_name_is_a_validation_error(client):
    r = client.post("/api/v1/projects", json={"name": "x", "url": "uat.example.gov.in"}, headers=CSRF)
    assert r.status_code == 422 and r.json()["ok"] is False and r.json()["error"]["code"] == "validation"


def test_creating_the_same_project_twice_returns_the_existing_one(client):
    body = {"name": "UR Portal", "url": "https://uat.example.gov.in"}
    assert client.post("/api/v1/projects", json=body, headers=CSRF).status_code == 201
    assert client.post("/api/v1/projects", json=body, headers=CSRF).status_code == 200


def test_the_demo_project_can_be_created(client):
    r = client.post("/api/v1/projects/demo", headers=CSRF)
    assert r.status_code == 201 and r.json()["data"]["slug"] == "demo"
    assert client.get("/api/v1/projects/demo").json()["data"]["name"]


@pytest.mark.parametrize("slug", ["..", "..%2F..%2Fetc", "nope"])
def test_unknown_or_escaping_slugs_are_404(client, slug):
    assert client.get(f"/api/v1/projects/{slug}").status_code == 404


# ---- runs -----------------------------------------------------------------------------------

def test_starting_a_run_spawns_the_pipeline_and_a_second_start_is_refused(client, fake_spawn):
    client.post("/api/v1/projects/demo", headers=CSRF)

    r = client.post("/api/v1/projects/demo/runs", json={"scope": "pipeline", "policy": "srs_wins", "auto_approve": True},
                    headers=CSRF)

    assert r.status_code == 202 and r.json()["data"]["status"] == "running"
    assert fake_spawn == [(["pipeline", "--policy", "srs_wins", "--auto-approve"], "pipeline")]
    again = client.post("/api/v1/projects/demo/runs", json={"scope": "pipeline"}, headers=CSRF)
    assert again.status_code == 409 and again.json()["error"]["code"] == "busy"


def test_a_single_stage_and_continue_are_valid_scopes_but_nonsense_is_not(client, fake_spawn):
    client.post("/api/v1/projects/demo", headers=CSRF)
    assert client.post("/api/v1/projects/demo/runs", json={"scope": "explore"}, headers=CSRF).status_code == 202
    assert client.post("/api/v1/projects/demo/runs", json={"scope": "rm -rf"}, headers=CSRF).status_code == 422


def test_runs_are_listed_and_a_log_tail_is_readable(client, fake_spawn):
    client.post("/api/v1/projects/demo", headers=CSRF)
    job = client.post("/api/v1/projects/demo/runs", json={"scope": "analyze"}, headers=CSRF).json()["data"]
    assert client.get("/api/v1/projects/demo/runs").json()["data"][0]["id"] == job["id"]
    assert client.get(f"/api/v1/projects/demo/runs/{job['id']}").json()["data"]["stage"] == "analyze"
    assert client.get(f"/api/v1/projects/demo/runs/{job['id']}/log").json()["data"]["log"] == ""
    assert client.get("/api/v1/projects/demo/runs/12345").status_code == 404


# ---- live -----------------------------------------------------------------------------------

def _write_events(p_state, session: str, n: int, worker: str = "main") -> None:
    d = p_state / "live" / session
    d.mkdir(parents=True, exist_ok=True)
    with (d / f"events-{worker}.jsonl").open("a", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(json.dumps({"t": time.time() + i, "seq": i, "w": worker, "agent": "explorer", "kind": "step",
                                 "title": f"step {i}"}) + "\n")


def test_live_sessions_and_cursor_paging(client):
    client.post("/api/v1/projects/demo", headers=CSRF)
    from agentqa.orchestrator.projects import open_project
    p, _ = open_project("demo")
    _write_events(p.state, "job-7-pipeline", 3)

    sessions = client.get("/api/v1/projects/demo/live/sessions").json()["data"]
    assert sessions[0]["id"] == "job-7-pipeline"
    first = client.get("/api/v1/projects/demo/live/job-7-pipeline/events").json()["data"]
    assert [e["title"] for e in first["events"]] == ["step 0", "step 1", "step 2"] and first["running"] is False
    _write_events(p.state, "job-7-pipeline", 1)
    more = client.get("/api/v1/projects/demo/live/job-7-pipeline/events", params={"cursor": first["cursor"]}).json()["data"]
    assert [e["title"] for e in more["events"]] == ["step 0"] and more["cursor"] != first["cursor"]


def test_live_stream_sends_events_as_sse_and_ends_when_nothing_runs(client):
    client.post("/api/v1/projects/demo", headers=CSRF)
    from agentqa.orchestrator.projects import open_project
    p, _ = open_project("demo")
    _write_events(p.state, "job-8-explore", 2)

    with client.stream("GET", "/api/v1/projects/demo/live/job-8-explore/stream") as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert body.count("event: live") == 1 and '"step 1"' in body and "event: end" in body


def test_live_session_and_shot_paths_cannot_escape(client):
    client.post("/api/v1/projects/demo", headers=CSRF)
    assert client.get("/api/v1/projects/demo/live/..%2F..%2Fx/events").status_code == 404
    from agentqa.orchestrator.projects import open_project
    p, _ = open_project("demo")
    _write_events(p.state, "job-9-run", 1)
    assert client.get("/api/v1/projects/demo/live/job-9-run/shots/..%2Fevents-main.jsonl").status_code == 404
