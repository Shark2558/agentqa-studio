"""M1.3: the board is one table (stages in pipeline order, the agent of each stage, owner-readable labels, helpers and
the three human gates) shared by the command line and the Live View, served at /live/board."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentqa import cli, live
from agentqa.ai import modes
from agentqa.api import create_app
from agentqa.api.auth import hash_password
from agentqa.api.settings import Settings
from agentqa.orchestrator import board

OWNER, PASSWORD = "owner@example.com", "correct horse battery staple"
CSRF = {"X-Requested-With": "AgentQA"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    settings = Settings(owner_email=OWNER, owner_password_hash=hash_password(PASSWORD), secret_key="s" * 40)
    return TestClient(create_app(settings))


def sign_in(c: TestClient) -> None:
    c.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD}, headers=CSRF)


def test_the_command_line_runs_the_boards_stages_in_the_boards_order():
    assert tuple(cli.STAGES) == board.STAGES
    assert board.STAGES[0] == "analyze" and board.STAGES[-1] == "report" and len(board.STAGES) == 12


def test_every_stage_has_an_agent_and_a_label_and_every_gate_names_a_real_stage():
    for stage in board.STAGES:
        assert board.STAGE_AGENT[stage] and board.LABELS[board.STAGE_AGENT[stage]]
    for gate in board.GATES:
        assert (gate.get("after") or gate.get("before")) in board.STAGES and gate["label"]
    assert {g["id"] for g in board.GATES} == {"questions", "plan", "defects"}
    for helpers in board.HELPERS.values():
        assert all(board.LABELS[h] for h in helpers)


def test_the_stage_events_are_emitted_under_the_boards_agent(monkeypatch, demo):
    p, s = demo
    seen = []
    monkeypatch.setattr(live, "emit", lambda agent, kind, title, **f: seen.append((agent, kind)))
    monkeypatch.setattr(cli, "_stage", lambda name, project, store, args: {"ok": True})
    for stage in ("write", "design", "heal", "run"):
        cli.stage(stage, p, s, None)
    starts = [a for a, k in seen if k == "stage_start"]
    assert starts == [board.STAGE_AGENT[x] for x in ("write", "design", "heal", "run")]
    assert starts == ["writer", "designer", "healer", "executor"]


def test_every_ai_agent_key_has_a_label_on_the_board():
    out = board.board(["citizen"])
    assert set(out["ai_labels"]) == set(modes.AGENTS)
    assert all(out["ai_labels"].values())


def test_the_board_lists_stages_in_order_with_labels_gates_helpers_and_roles():
    out = board.board(["citizen", "clerk"])
    assert [x["stage"] for x in out["stages"]] == list(board.STAGES)
    assert out["stages"][3] == {"stage": "write", "agent": "writer", "label": "Requirement Writer"}
    assert out["helpers"]["design"] == ["analyst", "casegen", "importer"]
    assert out["roles"] == ["citizen", "clerk"]
    assert [g["id"] for g in out["gates"]] == ["questions", "plan", "defects"]


def test_the_board_endpoint_needs_sign_in_and_a_real_project(client):
    assert client.get("/api/v1/projects/demo/live/board").status_code == 401
    sign_in(client)
    assert client.get("/api/v1/projects/nope/live/board").status_code == 404
    client.post("/api/v1/projects/demo", headers=CSRF)
    body = client.get("/api/v1/projects/demo/live/board").json()
    assert body["ok"] is True
    assert body["data"]["stages"][0]["label"] == "Requirement Analyst"
    assert "citizen" in body["data"]["roles"]
