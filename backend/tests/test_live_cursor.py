"""M1.3: the live cursor comes from the browser, so it is checked: only this run's event files, offsets clamped to the
file, at most 64 entries. A crafted cursor restarts or clamps; it never raises (500) and never reads outside the run."""
from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentqa.api import create_app
from agentqa.api.auth import hash_password
from agentqa.api.settings import Settings
from agentqa.orchestrator import live as L

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "recordings" / "cli-fixture-pipeline"
OWNER, PASSWORD = "owner@example.com", "correct horse battery staple"
CSRF = {"X-Requested-With": "AgentQA"}


def encode(value) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode()


@pytest.fixture
def run(tmp_path):
    d = tmp_path / "cli-fixture-pipeline"
    shutil.copytree(FIXTURE, d)
    return d


def main_count(d: Path) -> int:
    return len((d / "events-main.jsonl").read_text(encoding="utf-8").splitlines())


def test_a_good_cursor_resumes_after_what_was_read(run):
    events, token = L.read_events(run)
    assert len(events) == 447
    again, same = L.read_events(run, token)
    assert again == [] and set(L.decode_cursor(same)) == set(L.decode_cursor(token))


@pytest.mark.parametrize("bad", [
    {"events-main.jsonl": -1}, {"events-main.jsonl": "x"}, {"events-main.jsonl": True}, {"events-main.jsonl": 1.5},
    [1, 2], "text", None,
])
def test_a_negative_or_non_numeric_offset_restarts_that_file(run, bad):
    events, token = L.read_events(run, encode(bad))
    assert sum(1 for e in events if e["w"] == "main") == main_count(run)
    assert all(isinstance(v, int) and v >= 0 for v in L.decode_cursor(token).values())


def test_an_offset_past_the_end_is_clamped_to_the_file_size(run):
    size = (run / "events-main.jsonl").stat().st_size
    events, token = L.read_events(run, encode({"events-main.jsonl": 10 ** 12}))
    assert not any(e["w"] == "main" for e in events)
    assert L.decode_cursor(token)["events-main.jsonl"] == size


def test_unknown_or_escaping_file_names_are_dropped(run):
    events, token = L.read_events(run, encode({"../secret.jsonl": 5, "events-nope.jsonl": 3, "events-main.jsonl/..": 1}))
    assert len(events) == 447
    assert set(L.decode_cursor(token)) == {f.name for f in run.glob("events-*.jsonl")}


def test_a_cursor_with_too_many_entries_or_garbage_restarts_from_the_beginning(run):
    many = {f"events-w{i}.jsonl": 0 for i in range(100)}
    assert len(L.read_events(run, encode(many))[0]) == 447
    assert len(L.read_events(run, "%%%not-base64")[0]) == 447


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    settings = Settings(owner_email=OWNER, owner_password_hash=hash_password(PASSWORD), secret_key="s" * 40)
    c = TestClient(create_app(settings))
    c.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD}, headers=CSRF)
    c.post("/api/v1/projects/demo", headers=CSRF)
    from agentqa.orchestrator.projects import find_project
    p = find_project("demo")
    shutil.copytree(FIXTURE, p.state / "live" / "cli-fixture-pipeline")
    return c


def test_the_api_never_answers_500_to_a_crafted_cursor_and_refuses_a_huge_one(client):
    url = "/api/v1/projects/demo/live/cli-fixture-pipeline/events"
    for bad in (encode({"events-main.jsonl": -1}), encode({"events-main.jsonl": "x"}), "%%%"):
        r = client.get(url, params={"cursor": bad})
        assert r.status_code == 200 and len(r.json()["data"]["events"]) == 447
    assert client.get(url, params={"cursor": "a" * 4097}).status_code == 422
    with client.stream("GET", url.replace("/events", "/stream"), params={"cursor": encode({"x": -1})}) as r:
        assert r.status_code == 200
        assert "event: end" in "".join(r.iter_text())
