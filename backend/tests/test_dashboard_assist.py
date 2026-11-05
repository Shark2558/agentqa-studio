"""M1.4 Phase C — the old dashboard until Phase D removes it: its help box (still on the pages not yet moved) goes
through the new app's rules (who, caps, the Viewer rule), and its visual-review and heal pages, replaced in Phase C,
send a person to the new app instead of deciding anything (fresh-context security review, HIGH)."""
from __future__ import annotations

from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from agentqa.api import create_app
from agentqa.api.auth import COOKIE, User, hash_password
from agentqa.api.settings import Settings
from agentqa.store import Store, now

OWNER, PASSWORD = "owner@example.com", "correct horse battery staple"
WHO = f"{OWNER} (owner)"


@pytest.fixture
def old(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from agentqa.orchestrator import projects
    monkeypatch.setenv("AGENTQA_PROJECTS", str(tmp_path / "projects"))
    app = create_app(Settings(owner_email=OWNER, owner_password_hash=hash_password(PASSWORD), secret_key="s" * 40),
                     legacy=True)
    owner = TestClient(app, follow_redirects=False)
    assert owner.post("/api/v1/auth/login", json={"email": OWNER, "password": PASSWORD},
                      headers={"X-Requested-With": "AgentQA"}).status_code == 200
    projects.create_demo()
    p = projects.find_project("demo")

    def viewer() -> TestClient:
        c = TestClient(app, follow_redirects=False)
        c.cookies.set(COOKIE, app.state.sessions.issue(User(email="viewer@example.com", role="viewer")))
        return c
    return SimpleNamespace(owner=owner, viewer=viewer, project=p, db=lambda: closing(Store(p.db_path)))


def _ask(old, kind="takeover", **detail) -> int:
    with old.db() as s:
        return s.insert("assist", {"at": now(), "kind": kind, "role": "citizen", "agent": "explorer",
                                   "question": "Q" * 900, "detail": {"vw": 1280, "vh": 800, **detail},
                                   "status": "pending", "answer": None, "answered_at": None})


def test_a_viewer_gets_no_question_and_no_screenshot_from_the_old_box(old):
    aid = _ask(old, shot=None)
    assert old.viewer().get("/p/demo/assist/pending").json() == []
    assert old.viewer().get(f"/p/demo/assist/{aid}/shot").status_code == 403
    [q] = old.owner.get("/p/demo/assist/pending").json()
    assert q["id"] == aid and len(q["question"]) == 500 and q["shot"] is None


def test_the_old_box_points_its_screenshot_at_the_guarded_route(old):
    aid = _ask(old, shot="1-1.jpg", shot_v=4)
    [q] = old.owner.get("/p/demo/assist/pending").json()
    assert q["shot"] == f"/api/v1/projects/demo/assist/{aid}/shot?v=4"


@pytest.mark.parametrize("body", [{"kind": "type", "text": "x" * 2_000_000}, {"kind": "click", "x": 99_999_999, "y": -5},
                                  {"kind": "wave"}, {"kind": "press", "key": "F12"}])
def test_old_take_over_commands_follow_the_new_rules(old, body):
    aid = _ask(old)
    assert old.owner.post(f"/p/demo/assist/{aid}/cmd", json=body).status_code == 422


def test_old_take_over_commands_are_capped_and_logged_with_who(old):
    aid = _ask(old)
    assert all(old.owner.post(f"/p/demo/assist/{aid}/cmd", json={"kind": "back"}).status_code == 200
               for _ in range(20))
    assert old.owner.post(f"/p/demo/assist/{aid}/cmd", json={"kind": "back"}).status_code == 429
    assert old.owner.post(f"/p/demo/assist/{aid}", json={"done": True}).status_code == 200
    with old.db() as s:
        rows = [(r["change"], r["by"]) for r in s.all("SELECT change, by FROM change_log WHERE object='assist'")]
    assert rows == [("took over the explorer's browser as citizen", WHO), ("handed back the explorer's browser", WHO)]
    assert old.owner.post(f"/p/demo/assist/{aid}", json={"done": True}).status_code == 409
    assert old.owner.post("/p/demo/pause").status_code == 409                      # nothing is running


def test_the_old_visual_and_heal_pages_send_a_person_to_the_new_app_and_decide_nothing(old):
    with old.db() as s:
        s.insert("visual", {"key": "k", "role": "citizen", "path": "/apply", "status": "changed", "diff_ratio": 0.1,
                            "baseline": None, "current": None, "diff": None, "run_id": "r", "case_id": None,
                            "updated_at": now()})
        hid = s.insert("heals", {"case_id": "TC-0001", "run_id": "r", "kind": "locator", "old": {"field": "a"},
                                 "new": {"field": "b"}, "reason": "x", "status": "proposed", "created_at": now()})
    for method, path, page in (("GET", "/p/demo/visual", "visual"), ("GET", "/p/demo/heals", "heals"),
                               ("POST", "/p/demo/visual/k", "visual"), ("POST", "/p/demo/visual-approve-all", "visual"),
                               ("POST", f"/p/demo/heals/{hid}", "heals")):
        r = old.owner.request(method, path, data={"action": "approve"})
        assert r.status_code == 303 and r.headers["location"] == f"/app/projects/demo/{page}", (method, path)
    with old.db() as s:
        assert s.one("SELECT status FROM visual")["status"] == "changed"
        assert s.one("SELECT status FROM heals")["status"] == "proposed"
