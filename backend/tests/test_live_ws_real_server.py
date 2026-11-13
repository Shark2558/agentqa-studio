"""M1.3: the proof the test client cannot give. Starlette's TestClient runs WebSocket routes without any WebSocket
library, so this starts the real app on uvicorn and talks to it with the `websockets` client, as a browser would."""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from conftest import free_port

from agentqa.api import create_app
from agentqa.api.auth import COOKIE, hash_password
from agentqa.api.settings import Settings

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "recordings" / "cli-fixture-pipeline"
OWNER, PASSWORD = "owner@example.com", "correct horse battery staple"
CSRF = {"X-Requested-With": "AgentQA"}
START_TIMEOUT_S = 30


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    settings = Settings(owner_email=OWNER, owner_password_hash=hash_password(PASSWORD), secret_key="s" * 40)
    port = free_port()
    app = create_app(settings)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws_max_size=65536))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + START_TIMEOUT_S
    while not srv.started and time.time() < deadline:
        time.sleep(0.05)
    assert srv.started, "uvicorn did not start"
    base = f"127.0.0.1:{port}"
    with httpx.Client(base_url=f"http://{base}") as http:
        http.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD}, headers=CSRF)
        http.post("/api/v1/projects/demo", headers=CSRF)
        cookie = http.cookies[COOKIE]
    from agentqa.orchestrator.projects import find_project
    p = find_project("demo")
    shutil.copytree(FIXTURE, p.state / "live" / "cli-fixture-pipeline")

    yield base, cookie, app
    srv.should_exit = True
    thread.join(timeout=10)


def slots_open(app, count: int, seconds: float = 10.0) -> bool:
    """True once exactly `count` streams hold a slot. The first line of a stream can reach the client a moment before
    the server counts the slot (a busy machine shows it, GitHub's did), so a test must wait for the count, not read it."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if app.state.stream_slots.open_count() == count:
            return True
        time.sleep(0.05)
    return False


def slots_free(app, seconds: float = 10.0) -> bool:
    return slots_open(app, 0, seconds)


@pytest.fixture
def running(monkeypatch):
    """The fixture run reads as still going, so a stream stays open until the client leaves."""
    from agentqa.orchestrator import live
    monkeypatch.setattr(live, "is_running", lambda project, session: True)


def test_a_websocket_dropped_in_the_middle_of_a_run_frees_its_slot(server, running):
    base, cookie, app = server
    url = f"ws://{base}/api/v1/projects/demo/live/cli-fixture-pipeline/ws"
    ws = connect(url, origin=f"http://{base}", additional_headers={"Cookie": f"{COOKIE}={cookie}"}, open_timeout=10)
    assert json.loads(ws.recv(timeout=10))["type"] == "live"
    assert app.state.stream_slots.open_count() == 1
    ws.socket.close()                                         # no closing handshake: the network just goes away
    assert slots_free(app)


def test_an_sse_stream_closed_early_frees_its_slot(server, running):
    base, cookie, app = server
    with httpx.Client(base_url=f"http://{base}", headers={"Cookie": f"{COOKIE}={cookie}"}, timeout=10) as http:
        with http.stream("GET", "/api/v1/projects/demo/live/cli-fixture-pipeline/stream") as r:
            assert r.status_code == 200
            next(r.iter_lines())
            assert slots_open(app, 1), "the open stream never held a slot"
    assert slots_free(app)


def test_the_real_server_streams_a_run_over_a_websocket(server):
    base, cookie, app = server
    url = f"ws://{base}/api/v1/projects/demo/live/cli-fixture-pipeline/ws"
    with connect(url, origin=f"http://{base}", additional_headers={"Cookie": f"{COOKIE}={cookie}"},
                 open_timeout=10) as ws:
        first = json.loads(ws.recv(timeout=10))
        end = json.loads(ws.recv(timeout=10))
        with pytest.raises(ConnectionClosed) as closed:
            ws.recv(timeout=10)
    assert first["type"] == "live" and len(first["events"]) == 447
    assert end["type"] == "end" and end["reason"] == "finished"
    assert closed.value.rcvd is not None and closed.value.rcvd.code == 1000


def test_the_real_server_closes_a_signed_out_websocket_with_4401(server):
    base, _, _ = server
    url = f"ws://{base}/api/v1/projects/demo/live/cli-fixture-pipeline/ws"
    with connect(url, origin=f"http://{base}", open_timeout=10) as ws:
        with pytest.raises(ConnectionClosed) as closed:
            ws.recv(timeout=10)
    assert closed.value.rcvd is not None and closed.value.rcvd.code == 4401
