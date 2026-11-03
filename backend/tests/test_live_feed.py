"""M1.3: one live feed for both transports. It sends batches, then one `end` with the reason (finished, idle,
signed-out, gone); it never touches the event loop with blocking reads; and the number of open live streams is
capped per address and in total, each slot released exactly once however the stream ends."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentqa import store as store_module
from agentqa.api import create_app
from agentqa.api.auth import hash_password
from agentqa.api.live_feed import StreamSlots, live_feed
from agentqa.api.settings import Settings
from agentqa.orchestrator import NotFound
from agentqa.orchestrator import live as L

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "recordings" / "cli-fixture-pipeline"
OWNER, PASSWORD = "owner@example.com", "correct horse battery staple"
CSRF = {"X-Requested-With": "AgentQA"}
FAST = {"poll_s": 0.01}


def collect(gen) -> list[dict]:
    async def run():
        return [item async for item in gen]
    return asyncio.run(run())


@pytest.fixture
def recording(demo):
    p, _ = demo
    d = p.state / "live" / "cli-fixture-pipeline"
    shutil.copytree(FIXTURE, d)
    return p, d


def test_a_finished_run_is_sent_in_batches_then_ends_as_finished(recording):
    p, d = recording
    items = collect(live_feed(p, d, d.name, **FAST))
    assert [i["type"] for i in items] == ["live", "end"]
    assert len(items[0]["events"]) == 447 and all("phase" in e for e in items[0]["events"])
    assert items[-1]["reason"] == "finished" and items[-1]["cursor"] == items[0]["cursor"]


def test_a_feed_resumed_from_its_cursor_sends_only_what_is_new(recording):
    p, d = recording
    first = collect(live_feed(p, d, d.name, **FAST))
    again = collect(live_feed(p, d, d.name, first[0]["cursor"], **FAST))
    assert [i["type"] for i in again] == ["end"]


def test_a_silent_run_ends_after_the_idle_limit(recording, monkeypatch):
    p, d = recording
    first = collect(live_feed(p, d, d.name, **FAST))
    monkeypatch.setattr(L, "is_running", lambda project, session: True)
    items = collect(live_feed(p, d, d.name, first[0]["cursor"], idle_limit_s=0.05, **FAST))
    assert items == [{"type": "end", "cursor": first[0]["cursor"], "reason": "idle"}]


def test_an_expired_sign_in_ends_the_feed(recording, monkeypatch):
    p, d = recording
    monkeypatch.setattr(L, "is_running", lambda project, session: True)
    items = collect(live_feed(p, d, d.name, signed_in=lambda: False, auth_check_s=0, **FAST))
    assert items[-1]["reason"] == "signed-out"


def test_a_run_whose_folder_was_pruned_ends_as_gone(recording, monkeypatch):
    p, d = recording

    def pruned(project, session):
        raise NotFound("No such live session")
    monkeypatch.setattr(L, "is_running", pruned)
    items = collect(live_feed(p, d, d.name, **FAST))
    assert items[-1]["reason"] == "gone"


def test_stream_slots_cap_each_address_and_the_total_and_release_once():
    slots = StreamSlots(per_client=2, total=3)
    a1, a2 = slots.lease("a"), slots.lease("a")
    assert a1 and a2 and slots.lease("a") is None
    b1 = slots.lease("b")
    assert b1 and slots.lease("c") is None                     # the total cap
    a1.release()
    a1.release()                                               # twice is harmless: one slot back, not two
    assert slots.open_count("a") == 1 and slots.open_count() == 2
    assert slots.lease("c") and slots.lease("c") is None


# ---- through the API -------------------------------------------------------------------------------------------

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


STREAM = "/api/v1/projects/demo/live/cli-fixture-pipeline/stream"


def test_the_sse_stream_ends_with_its_reason_and_releases_its_slot(client):
    with client.stream("GET", STREAM) as r:
        body = "".join(r.iter_text())
    assert body.count("event: live") == 1 and "event: end" in body and '"reason": "finished"' in body
    assert client.app.state.stream_slots.open_count() == 0


def test_a_fifth_open_stream_from_one_address_is_refused(client):
    slots = client.app.state.stream_slots
    held = [slots.lease("testclient") for _ in range(4)]
    assert all(held)
    r = client.get(STREAM)
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_streams"
    held[0].release()
    with client.stream("GET", STREAM) as r:
        assert r.status_code == 200 and "event: end" in "".join(r.iter_text())


def test_the_stream_never_opens_the_project_store(client, monkeypatch):
    """The stream needs only folders and one row of the jobs table (read with a bare query), so the full store, with
    its schema set-up on every open, is never opened while a run is watched."""
    def no_store(self, *a, **k):
        raise AssertionError("opened the full project store while streaming")
    monkeypatch.setattr(store_module.Store, "__init__", no_store)
    with client.stream("GET", STREAM) as r:
        assert r.status_code == 200 and "event: end" in "".join(r.iter_text())


# ---- M1.3 review fixes: errors on Windows / Drive, big reads, slots after a failure ------------------------------

def test_a_folder_that_vanished_mid_feed_ends_as_gone(recording, monkeypatch):
    p, d = recording

    def vanished(folder, cursor=""):
        raise FileNotFoundError(2, "No such file or directory")
    monkeypatch.setattr(L, "read_events", vanished)
    assert collect(live_feed(p, d, d.name, **FAST))[-1]["reason"] == "gone"


def test_a_passing_read_error_is_retried_not_reported_as_gone(recording, monkeypatch):
    p, d = recording
    real, calls = L.read_events, {"n": 0}

    def flaky(folder, cursor=""):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return real(folder, cursor)
    monkeypatch.setattr(L, "read_events", flaky)
    items = collect(live_feed(p, d, d.name, **FAST))
    assert sum(len(i.get("events", [])) for i in items) == 447 and items[-1]["reason"] == "finished"


def test_a_locked_store_while_checking_is_retried(recording, monkeypatch):
    import sqlite3
    p, d = recording
    calls = {"n": 0}

    def locked_once(project, session):
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return False
    monkeypatch.setattr(L, "is_running", locked_once)
    first = collect(live_feed(p, d, d.name, **FAST))
    calls["n"] = 0
    items = collect(live_feed(p, d, d.name, first[-1]["cursor"], **FAST))
    assert calls["n"] == 2 and items == [{"type": "end", "cursor": first[-1]["cursor"], "reason": "finished"}]


def test_big_reads_go_out_in_capped_batches_and_only_the_last_moves_the_cursor(recording):
    p, d = recording
    items = collect(live_feed(p, d, d.name, max_batch=100, **FAST))
    batches = [i for i in items if i["type"] == "live"]
    assert [len(b["events"]) for b in batches] == [100, 100, 100, 100, 47]
    assert [b["cursor"] for b in batches[:-1]] == [""] * 4          # a reconnect mid-read re-reads, never skips
    assert batches[-1]["cursor"] == items[-1]["cursor"] != ""


def test_a_feed_that_fails_mid_stream_still_frees_its_sse_slot(client, monkeypatch):
    async def broken(*a, **k):
        yield {"type": "live", "events": [], "cursor": ""}
        raise ValueError("a bug in the feed")
    monkeypatch.setattr("agentqa.api.routes_live.live_feed", broken)
    with pytest.raises(ValueError):
        with client.stream("GET", STREAM) as r:
            "".join(r.iter_text())
    assert client.app.state.stream_slots.open_count() == 0
