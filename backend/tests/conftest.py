"""Shared fixtures for AgentQA's own tests. They need no browser and no running portal."""
from __future__ import annotations

import json
import shutil
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentqa.config import Project  # noqa: E402
from agentqa.store import Store  # noqa: E402


@pytest.fixture
def demo(tmp_path):
    """A fresh copy of the demo project: (Project, Store)."""
    root = tmp_path / "demo"
    (root / "srs").mkdir(parents=True)
    shutil.copy(ROOT / "demo" / "project.yaml", root / "project.yaml")
    for f in (ROOT / "demo" / "srs").glob("*.docx"):
        shutil.copy(f, root / "srs" / f.name)
    p = Project(root)
    store = Store(p.db_path)
    yield p, store
    store.close()                     # closing twice is harmless; an open file would hold the folder on Windows


@pytest.fixture
def explored(demo):
    """The demo project with the app map a real Explorer run produced (tests/fixtures/demo_screens.json)."""
    p, s = demo
    for row in json.loads((ROOT / "tests" / "fixtures" / "demo_screens.json").read_text(encoding="utf-8")):
        text = json.dumps(row).replace("{base}", p.base_url)
        s.insert("screens", json.loads(text))
    return p, s


GATES_OWNER, GATES_PASSWORD = "owner@example.com", "correct horse battery staple"
GATES_WHO = f"{GATES_OWNER} (owner)"
CSRF = {"X-Requested-With": "AgentQA"}


@pytest.fixture
def gates(tmp_path, monkeypatch):
    """The API with a signed-in owner, and the demo project holding the gates fixture (M1.4). `db()` opens the
    project store (use it in a `with`), `as_role(role)` is a client signed in with that role, `busy()` leaves a job
    running, and `spawned` lists the jobs the API would have started."""
    from contextlib import closing
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from agentqa.api import create_app
    from agentqa.api.auth import COOKIE, User, hash_password
    from agentqa.api.settings import Settings
    from agentqa.orchestrator import jobs, projects
    from gates_fixture import load

    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    app = create_app(Settings(owner_email=GATES_OWNER, owner_password_hash=hash_password(GATES_PASSWORD),
                              secret_key="s" * 40))
    client = TestClient(app)
    signed_in = client.post("/api/v1/auth/login", json={"email": GATES_OWNER, "password": GATES_PASSWORD}, headers=CSRF)
    assert signed_in.status_code == 200, signed_in.text
    projects.create_demo()
    p = projects.find_project("demo")
    s = Store(p.db_path)
    counts = load(p, s)
    s.close()
    spawned: list[tuple[list[str], str]] = []

    def fake_spawn(project, store, args, label, headed=False, shots=None):
        if jobs.running(store):
            raise jobs.Busy("A stage is already running for this project.")
        spawned.append((args, label))
        return store.insert("jobs", {"stage": label, "status": "running", "started_at": "2026-11-04T10:00:00",
                                     "log_path": "", "pid": 999_999_999})

    def as_role(role: str) -> TestClient:
        c = TestClient(app)
        c.cookies.set(COOKIE, app.state.sessions.issue(User(email=f"{role}@example.com", role=role)))
        return c

    def busy() -> None:
        with closing(Store(p.db_path)) as st:
            st.insert("jobs", {"stage": "pipeline", "status": "running", "started_at": "2026-11-04T10:00:00",
                               "log_path": "", "pid": 999_999_999})

    for module in ("agentqa.api.routes_runs", "agentqa.api.routes_questions"):
        monkeypatch.setattr(f"{module}.spawn", fake_spawn)        # fails loudly if the name moves: no real process
    monkeypatch.setattr("agentqa.orchestrator.jobs.pid_alive", lambda pid: True)
    return SimpleNamespace(client=client, app=app, project=p, counts=counts, base="/api/v1/projects/demo",
                           db=lambda: closing(Store(p.db_path)), as_role=as_role, busy=busy, spawned=spawned)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
