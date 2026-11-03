"""M1.3: the Live View's WebSocket. The HTTP guards never see a WebSocket, so the route checks for itself: the sign-in
cookie, an Origin equal to the host (cross-site WebSocket hijacking), the rate limit and the open-stream cap. Refusals
are a close code after the handshake (4401 signed out, 4403 other site, 4404 no such run, 4429 too many), never data.
Messages from the browser are read and dropped; one over 1 KB closes the socket."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agentqa.api import create_app
from agentqa.api.auth import COOKIE, User, hash_password
from agentqa.api.ratelimit import RateLimiter
from agentqa.api.settings import Settings
from agentqa.orchestrator import live as L

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "recordings" / "cli-fixture-pipeline"
OWNER, PASSWORD = "owner@example.com", "correct horse battery staple"
CSRF = {"X-Requested-With": "AgentQA"}
SAME_SITE = {"origin": "http://testserver"}
URL = "/api/v1/projects/demo/live/cli-fixture-pipeline/ws"


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
    c.run_dir = p.state / "live" / "cli-fixture-pipeline"
    return c


def closed_with(c: TestClient, url: str = URL, **kw) -> int:
    with c.websocket_connect(url, **kw) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    return closed.value.code


def test_the_owner_gets_the_run_in_batches_then_end_then_a_normal_close(client):
    with client.websocket_connect(URL, headers=SAME_SITE) as ws:
        first = ws.receive_json()
        end = ws.receive_json()
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert first["type"] == "live" and len(first["events"]) == 447 and all("phase" in e for e in first["events"])
    assert end == {"type": "end", "cursor": first["cursor"], "reason": "finished"}
    assert closed.value.code == 1000
    assert client.app.state.stream_slots.open_count() == 0


def test_a_viewer_may_watch(client):
    viewer = TestClient(client.app)
    viewer.cookies.set(COOKIE, client.app.state.sessions.issue(User(email="v@example.com", role="viewer")))
    with viewer.websocket_connect(URL, headers=SAME_SITE) as ws:
        assert ws.receive_json()["type"] == "live"


def test_resuming_from_a_cursor_sends_only_the_end(client):
    with client.websocket_connect(URL, headers=SAME_SITE) as ws:
        cursor = ws.receive_json()["cursor"]
    with client.websocket_connect(f"{URL}?cursor={cursor}", headers=SAME_SITE) as ws:
        assert ws.receive_json()["type"] == "end"


def test_signed_out_is_4401(client):
    assert closed_with(TestClient(client.app), headers=SAME_SITE) == 4401


@pytest.mark.parametrize("headers", [{}, {"origin": "https://evil.example"}, {"origin": "http://testserver.evil.example"},
                                     {"origin": "null"}, {"origin": "http://testserver:8800"}, {"origin": "http://["}])
def test_another_site_or_no_origin_is_4403(client, headers):
    assert closed_with(client, headers=headers) == 4403


@pytest.mark.parametrize("url", ["/api/v1/projects/demo/live/job-404-nothing/ws",
                                 "/api/v1/projects/nope/live/cli-fixture-pipeline/ws"])
def test_an_unknown_run_or_project_is_4404(client, url):
    assert closed_with(client, url, headers=SAME_SITE) == 4404


def test_a_path_that_tries_to_leave_the_live_folder_never_opens(client):
    with pytest.raises(WebSocketDisconnect):                 # no route matches: the handshake itself is refused
        with client.websocket_connect("/api/v1/projects/demo/live/..%2F..%2Fx/ws", headers=SAME_SITE) as ws:
            ws.receive_text()


@pytest.mark.parametrize("session", ["..", "../..", "..\\..\\x", "/etc", "cli-fixture-pipeline/../.."])
def test_the_run_lookup_the_socket_uses_refuses_anything_outside_the_live_folder(client, session):
    from agentqa.api.errors import ApiError
    from agentqa.api.routes_live import open_run
    with pytest.raises(ApiError) as refused:
        open_run("demo", session)
    assert refused.value.status == 404


def wait_until(check, seconds: float = 5.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return check()


def test_a_feed_that_fails_closes_with_1011_and_frees_its_slot(client, monkeypatch):
    async def broken(*a, **k):
        yield {"type": "live", "events": [], "cursor": ""}
        raise ValueError("a bug in the feed")
    monkeypatch.setattr("agentqa.api.routes_live_ws.live_feed", broken)
    with client.websocket_connect(URL, headers=SAME_SITE) as ws:
        assert ws.receive_json()["type"] == "live"
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 1011
    assert wait_until(lambda: client.app.state.stream_slots.open_count() == 0)


def test_leaving_in_the_middle_of_a_run_frees_the_slot(client, monkeypatch):
    monkeypatch.setattr(L, "is_running", lambda project, session: True)
    with client.websocket_connect(URL, headers=SAME_SITE) as ws:
        assert ws.receive_json()["type"] == "live"
    assert wait_until(lambda: client.app.state.stream_slots.open_count() == 0)


def test_a_huge_cursor_is_refused(client):
    assert closed_with(client, f"{URL}?cursor={'a' * 5000}", headers=SAME_SITE) == 4400


def test_too_many_streams_or_requests_is_4429(client):
    slots = client.app.state.stream_slots
    held = [slots.lease("testclient") for _ in range(4)]
    assert closed_with(client, headers=SAME_SITE) == 4429
    for lease in held:
        lease.release()
    client.app.state.rate_limiter = RateLimiter(per_minute=0)
    assert closed_with(client, headers=SAME_SITE) == 4429


def append(run_dir: Path, title: str) -> None:
    with (run_dir / "events-main.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": time.time(), "seq": 99999, "w": "main", "agent": "srs", "kind": "start",
                             "title": title}) + "\n")


def test_small_messages_from_the_browser_are_ignored_and_the_feed_goes_on(client, monkeypatch):
    monkeypatch.setattr(L, "is_running", lambda project, session: True)
    with client.websocket_connect(URL, headers=SAME_SITE) as ws:
        assert ws.receive_json()["type"] == "live"
        ws.send_text("ping")
        append(client.run_dir, "late event")
        later = ws.receive_json()
    assert later["type"] == "live" and [e["title"] for e in later["events"]] == ["late event"]


def test_a_message_over_1_kb_closes_the_socket(client, monkeypatch):
    monkeypatch.setattr(L, "is_running", lambda project, session: True)
    with client.websocket_connect(URL, headers=SAME_SITE) as ws:
        assert ws.receive_json()["type"] == "live"
        ws.send_text("x" * 2048)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 1009
