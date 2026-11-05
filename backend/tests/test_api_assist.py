"""M1.4 Phase C — the help box ("AgentQA needs you"), take-over, pause and the teach routes, through the API.

The pending list is capped and never carries an answer; an answer is exactly one action and fits its question; a
take-over command is checked (inside the screen, allowed keys, in-scope addresses, at most 20 waiting) before the agent
sees it; nothing typed reaches a log row, a recording or the database file; a Viewer sees who waits, not the screen."""
from __future__ import annotations

import json

import pytest

from agentqa import assist, live
from agentqa.api import SHOT_PATH
from agentqa.store import now
from assist_fakes import JPEG, FakePage, file_bytes, in_thread, wait_until
from conftest import CSRF, GATES_WHO

MARKER = "Zq7-typed-secret-41"


def _ask(g, kind="otp", status="pending", answer=None, **detail) -> int:
    with g.db() as s:
        return s.insert("assist", {"at": now(), "kind": kind, "role": "citizen", "agent": "explorer",
                                   "question": detail.pop("question", f"A {kind} question"), "detail": detail,
                                   "status": status, "answer": answer, "answered_at": None})


def _items(g, client=None) -> list[dict]:
    r = (client or g.client).get(f"{g.base}/assist")
    assert r.status_code == 200, r.text
    return r.json()["data"]["items"]


def _answer(g, aid, body):
    return g.client.post(f"{g.base}/assist/{aid}/answer", json=body, headers=CSRF)


def _command(g, aid, body):
    return g.client.post(f"{g.base}/assist/{aid}/commands", json=body, headers=CSRF)


def _log(g) -> list[dict]:
    with g.db() as s:
        return s.all("SELECT object, object_id, change, justification, by FROM change_log WHERE object IN "
                     "('assist', 'run') ORDER BY id")


def test_the_pending_list_is_capped_and_never_carries_an_answer(gates):
    _ask(gates, status="answered", answer={"text": MARKER})
    aid = _ask(gates, "navigate", question="Q" * 900, hint="h" * 2000, options=["o" * 300] * 30,
               clickables=[{"text": "c" * 300, "x": 1, "y": 2}] * 60 + [{"text": "no place", "x": None}, "junk"],
               fields=[{"label": "f", "type": "password", "x": 3, "y": 4, "filled": 1}] * 30,
               log=["l" * 300] * 20, url="http://127.0.0.1:8800/" + "a" * 3000, vw=1280, vh=800, shot="1-1.jpg", shot_v=3)
    r = gates.client.get(f"{gates.base}/assist")
    data = r.json()["data"]
    assert data["paused"] == {"on": False, "at": None, "by": None}
    [q] = data["items"]
    assert q["id"] == aid and len(q["question"]) == 500 and len(q["hint"]) == 1000
    assert len(q["options"]) == 20 and {len(o) for o in q["options"]} == {200}
    assert len(q["clickables"]) == 40 and q["clickables"][0] == {"text": "c" * 200, "x": 1, "y": 2}
    assert len(q["fields"]) == 20 and q["fields"][0] == {"label": "f", "type": "password", "x": 3, "y": 4, "filled": True}
    assert len(q["log"]) == 12 and {len(line) for line in q["log"]} == {200}
    assert len(q["url"]) == 2000 and q["shot_v"] == 3 and q["has_shot"] is True and q["production"] is False
    assert "answer" not in q and MARKER not in r.text and "1-1.jpg" not in r.text
    assert SHOT_PATH.match(f"{gates.base}/assist")                               # polled: the screenshot bucket


def test_a_viewer_sees_who_is_waiting_but_not_the_screen(gates):
    aid = _ask(gates, "navigate", options=["Citizen Login"], url="http://127.0.0.1:8800/", shot=None)
    viewer = gates.as_role("viewer")
    assert _items(gates, viewer) == [{"id": aid, "kind": "navigate", "role": "citizen", "agent": "explorer",
                                      "at": _items(gates)[0]["at"]}]
    assert viewer.get(f"{gates.base}/assist/{aid}/shot").status_code == 403
    assert viewer.post(f"{gates.base}/assist/{aid}/answer", json={"skip": True}, headers=CSRF).status_code == 403


@pytest.mark.parametrize("body", [{}, {"text": "1", "ok": True}, {"x": 5}, {"skip": False}, {"text": ""},
                                  {"text": "a" * 201}, {"option": -1}, {"nope": 1}, {"text": "a\nb"},
                                  {"x": "Infinity", "y": 1}, {"takeover": True, "done": True}])
def test_an_answer_is_exactly_one_action(gates, body):
    aid = _ask(gates, "navigate", options=["A", "B"])
    assert _answer(gates, aid, body).status_code == 422


def test_an_answer_must_fit_its_question(gates):
    assert _answer(gates, _ask(gates, "otp"), {"ok": True}).status_code == 422
    assert _answer(gates, _ask(gates, "takeover"), {"text": "x"}).status_code == 422
    nav = _ask(gates, "navigate", options=["A", "B"], vw=1280, vh=800)
    assert _answer(gates, nav, {"option": 2}).status_code == 422
    assert _answer(gates, nav, {"x": 1281, "y": 5}).status_code == 422
    assert _answer(gates, nav, {"x": 640, "y": 212, "text": "Citizen Login"}).status_code == 200
    assert _log(gates)[-1]["change"] == "answered the explorer's navigate question: clicked at (640, 212)"


def test_an_answer_counts_once_hides_its_value_in_the_log_and_out_of_time_is_409(gates):
    aid = _ask(gates, "otp", secret=True)
    assert _answer(gates, aid, {"text": "907315"}).json()["data"] == {"id": aid, "status": "answered"}
    with gates.db() as s:
        assert s.one("SELECT answer FROM assist WHERE id=?", [aid])["answer"] == {"text": "907315",
                                                                                 "via": f"app {GATES_WHO}"}
    assert _answer(gates, aid, {"text": "1"}).status_code == 409
    assert _answer(gates, _ask(gates, status="expired"), {"text": "1"}).status_code == 409
    assert _answer(gates, 999_999, {"skip": True}).status_code == 404
    assert _log(gates) == [{"object": "assist", "object_id": str(aid), "by": GATES_WHO, "justification": "",
                            "change": "answered the explorer's otp question (value hidden)"}]
    assert "907315" not in json.dumps(_log(gates))


def test_take_over_answers_and_skips_are_logged_in_plain_words(gates):
    _answer(gates, _ask(gates, "navigate"), {"takeover": True})
    _answer(gates, _ask(gates, "captcha"), {"skip": True})
    _answer(gates, _ask(gates, "takeover"), {"done": True})
    _answer(gates, _ask(gates, "takeover"), {"skip": True})
    assert [x["change"] for x in _log(gates)] == [
        "asked to take over the explorer's browser", "skipped the explorer's captcha question",
        "handed back the explorer's browser", "cancelled the take-over of the explorer's browser"]


@pytest.mark.parametrize("body", [{"kind": "click", "x": 1281, "y": 5}, {"kind": "click", "x": -1, "y": 5},
                                  {"kind": "wave"}, {"kind": "press", "key": "F12"}, {"kind": "type", "text": ""},
                                  {"kind": "type", "text": "a" * 501}, {"kind": "scroll", "dy": 6000},
                                  {"kind": "goto", "path": "https://evil.example/"}, {"kind": "goto", "path": "apply"},
                                  {"kind": "goto", "path": "/a\nb"}, {"kind": "back", "extra": 1}])
def test_a_command_outside_the_rules_is_refused(gates, body):
    aid = _ask(gates, "takeover", vw=1280, vh=800)
    assert _command(gates, aid, body).status_code == 422


def test_an_address_outside_the_test_scope_is_refused(gates, monkeypatch):
    from agentqa.config import Project
    monkeypatch.setattr(Project, "in_scope", lambda self, path: not path.endswith("/logout"))
    aid = _ask(gates, "takeover")
    r = _command(gates, aid, {"kind": "goto", "path": "/logout"})
    assert r.status_code == 422 and "outside the test scope" in r.json()["error"]["message"]
    assert _command(gates, aid, {"kind": "goto", "path": "/apply"}).status_code == 202


def test_commands_queue_in_order_and_the_first_one_is_logged_as_taking_over(gates):
    aid = _ask(gates, "takeover", vw=1280, vh=800)
    bodies = [{"kind": "click", "x": 10, "y": 20}, {"kind": "type", "text": "9876543210"},
              {"kind": "press", "key": "Enter"}, {"kind": "scroll", "dy": -400}, {"kind": "back"},
              {"kind": "goto", "path": "/apply"}]
    ids = [_command(gates, aid, b).json()["data"]["id"] for b in bodies]
    assert ids == sorted(ids)
    with gates.db() as s:
        kinds = [r["cmd"]["kind"] for r in s.all("SELECT cmd FROM assist_cmds WHERE assist_id=? ORDER BY id", [aid])]
    assert kinds == ["click", "type", "press", "scroll", "back", "goto"]
    assert [x["change"] for x in _log(gates)] == ["took over the explorer's browser as citizen"]
    assert _command(gates, _ask(gates, "navigate"), {"kind": "back"}).status_code == 409
    assert _command(gates, _ask(gates, "takeover", status="answered"), {"kind": "back"}).status_code == 409


def test_a_21st_waiting_command_is_refused(gates):
    aid = _ask(gates, "takeover")
    assert all(_command(gates, aid, {"kind": "back"}).status_code == 202 for _ in range(20))
    r = _command(gates, aid, {"kind": "back"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many"


def test_the_allowed_keys_are_the_engines(gates):
    from agentqa.api.schemas_review import KEYS
    assert set(KEYS) == assist.KEYS


def test_the_screenshot_goes_by_id_with_no_store_and_a_planted_name_is_refused(gates):
    folder = gates.project.state / "assist"
    folder.mkdir(parents=True, exist_ok=True)
    aid = _ask(gates, "takeover")
    (folder / f"{aid}-1.jpg").write_bytes(JPEG)
    with gates.db() as s:
        s.update("assist", "id", aid, {"detail": {"shot": f"{aid}-1.jpg", "shot_v": 1}})
    r = gates.client.get(f"{gates.base}/assist/{aid}/shot", params={"v": 1})
    assert r.status_code == 200 and r.content == JPEG and r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"
    assert SHOT_PATH.match(f"{gates.base}/assist/{aid}/shot")
    (gates.project.root / "secret.jpg").write_bytes(JPEG)
    for planted in ("../../secret.jpg", "x.png", f"{aid}-1.jpg/../../../secret.jpg", None):
        with gates.db() as s:
            s.update("assist", "id", aid, {"detail": {"shot": planted}})
        assert gates.client.get(f"{gates.base}/assist/{aid}/shot").status_code == 404, planted
    done = _ask(gates, "takeover", status="answered", shot=f"{aid}-1.jpg")
    assert gates.client.get(f"{gates.base}/assist/{done}/shot").status_code == 404


def test_pause_needs_a_run_and_resume_hands_back_every_browser(gates):
    r = gates.client.post(f"{gates.base}/pause", json={}, headers=CSRF)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_running"
    gates.busy()
    r = gates.client.post(f"{gates.base}/pause", json={}, headers=CSRF)
    assert r.status_code == 200 and r.json()["data"]["on"] is True and r.json()["data"]["by"] == GATES_WHO
    assert gates.client.get(f"{gates.base}/assist").json()["data"]["paused"]["by"] == GATES_WHO
    aid = _ask(gates, "takeover")
    r = gates.client.post(f"{gates.base}/resume", json={}, headers=CSRF)
    assert r.json()["data"] == {"on": False, "at": None, "by": None, "handed_back": 1}
    with gates.db() as s:
        assert s.one("SELECT answer FROM assist WHERE id=?", [aid])["answer"] == {"done": True, "via": f"app {GATES_WHO}"}
    assert not assist.paused(gates.project)
    assert [x["change"] for x in _log(gates)] == ["paused every agent", "resumed and handed back 1 browser(s)"]
    assert gates.client.post(f"{gates.base}/pause", json={"why": 1}, headers=CSRF).status_code == 422


def test_a_planted_typed_secret_reaches_no_log_row_no_recording_and_not_the_database_file(gates, tmp_path, monkeypatch):
    folder = tmp_path / "recording"
    monkeypatch.setattr(live, "_LIVE", live.Live(folder, "test"))
    page = FakePage(focus="password")
    thread, out = in_thread(lambda: assist.takeover(gates.project, page, role="clerk", agent="login",
                                                    question="Log in as clerk", timeout=20))
    aid = wait_until(lambda: next((q["id"] for q in _items(gates) if q["kind"] == "takeover"), None))
    cid = _command(gates, aid, {"kind": "type", "text": MARKER}).json()["data"]["id"]     # "hide" not ticked
    with gates.db() as s:
        wait_until(lambda: s.one("SELECT status FROM assist_cmds WHERE id=?", [cid])["status"] == "done")
    assert _answer(gates, aid, {"done": True}).status_code == 200
    thread.join(10)
    assert out["result"]["done"] is True and page.keyboard.typed == [MARKER]
    with gates.db() as s:
        rows = json.dumps(s.all("SELECT * FROM change_log")) + json.dumps(s.all("SELECT * FROM assist_cmds")) \
            + json.dumps(s.all("SELECT * FROM assist"))
    recorded = "".join(f.read_text(encoding="utf-8") for f in folder.glob("*.jsonl"))
    assert MARKER not in rows and MARKER not in recorded and "Typed 19 character(s)" in recorded
    assert MARKER.encode() not in file_bytes(gates.project.db_path)


def test_teach_routes_check_the_role_and_start_a_job_with_a_visible_browser(gates):
    r = gates.client.post(f"{gates.base}/accounts/citizen/teach", json={}, headers=CSRF)
    assert r.status_code == 202 and r.json()["data"]["stage"] == "teach-citizen"
    assert gates.spawned[-1] == (["teach-login", "--role", "citizen"], "teach-citizen") and gates.headed[-1] is True
    assert gates.client.post(f"{gates.base}/accounts/nobody/teach", json={}, headers=CSRF).status_code == 422
    assert gates.client.post(f"{gates.base}/accounts/a%20b/teach", json={}, headers=CSRF).status_code == 422
    assert gates.client.post(f"{gates.base}/explore/teach", json={"role": "nobody"}, headers=CSRF).status_code == 422
    r = gates.client.post(f"{gates.base}/explore/teach", json={"role": "citizen"}, headers=CSRF)
    assert r.status_code == 409                                                  # the teach-login job still runs
    with gates.db() as s:
        s.exec("UPDATE jobs SET status='done'")
    r = gates.client.post(f"{gates.base}/explore/teach", json={"role": "citizen"}, headers=CSRF)
    assert r.status_code == 202 and gates.spawned[-1] == (["teach-nav", "--role", "citizen"], "teach-nav-citizen")


# ---- review fixes (Phase C, fresh-context reviews) -----------------------------------------------------------

def test_a_confirm_question_takes_a_choice_as_the_visual_check_asks_it(gates):
    aid = _ask(gates, "confirm", options=["Yes, the page shows it", "No, it does not"])
    assert _answer(gates, aid, {"option": 2}).status_code == 422
    assert _answer(gates, aid, {"option": 1}).status_code == 200
    assert _answer(gates, _ask(gates, "confirm"), {"ok": True}).status_code == 200


def test_the_newest_twenty_questions_are_listed_oldest_first(gates):
    ids = [_ask(gates, "otp") for _ in range(25)]
    assert [q["id"] for q in _items(gates)] == ids[-20:]


def test_a_production_application_is_flagged_and_a_flag_that_cannot_be_read_counts_as_production(gates, monkeypatch):
    path = gates.project.config_path
    path.write_text(path.read_text(encoding="utf-8").replace("environment: Test / QA", "environment: Production", 1),
                    encoding="utf-8")
    _ask(gates, "takeover", url="http://127.0.0.1:8800/apply")
    assert _items(gates)[0]["production"] is True
    from agentqa.config import Project

    def broken(self, path_or_app):
        raise KeyError(path_or_app)
    monkeypatch.setattr(Project, "is_production", broken)
    assert _items(gates)[0]["production"] is True


def test_the_sweep_runs_at_most_once_a_minute_and_never_fails_the_list(gates, monkeypatch):
    import sqlite3

    from agentqa.orchestrator.gates import helpbox
    calls = []

    def locked(store, **kw):
        calls.append(kw)
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(helpbox, "_SWEPT", {})
    monkeypatch.setattr(assist, "expire_stale", locked)
    aid = _ask(gates, "otp")
    assert [[q["id"] for q in _items(gates)] for _ in range(3)] == [[aid]] * 3
    assert len(calls) == 1 and calls[0]["shots"] == gates.project.state / "assist"


def test_twenty_commands_at_once_still_stop_at_twenty(gates):
    from concurrent.futures import ThreadPoolExecutor
    aid = _ask(gates, "takeover")
    with ThreadPoolExecutor(max_workers=12) as pool:
        codes = list(pool.map(lambda _: _command(gates, aid, {"kind": "back"}).status_code, range(40)))
    assert codes.count(202) == 20 and set(codes) == {202, 429}
    with gates.db() as s:
        assert s.scalar("SELECT COUNT(*) FROM assist_cmds WHERE assist_id=?", [aid]) == 20


def test_a_screenshot_named_for_another_question_is_refused(gates):
    folder = gates.project.state / "assist"
    folder.mkdir(parents=True, exist_ok=True)
    other = _ask(gates, "takeover")
    (folder / f"{other}-1.jpg").write_bytes(JPEG)
    aid = _ask(gates, "takeover", shot=f"{other}-1.jpg")
    assert gates.client.get(f"{gates.base}/assist/{aid}/shot").status_code == 404


@pytest.mark.parametrize("path", ["/x/../admin", "/./admin", "//admin", "/%61dmin", "/a\\b/admin", "/admin%2f.."])
def test_an_address_that_steps_out_of_the_scope_is_refused(gates, monkeypatch, path):
    import re

    from agentqa.config import Project
    monkeypatch.setattr(Project, "in_scope", lambda self, p: not re.search(r"^/admin", p))
    aid = _ask(gates, "takeover")
    assert _command(gates, aid, {"kind": "goto", "path": path}).status_code == 422
    assert _command(gates, aid, {"kind": "goto", "path": "/apply?x=%20y"}).status_code == 202


def test_a_database_that_cannot_be_read_answers_503_not_an_empty_list(gates, monkeypatch):
    import sqlite3

    from agentqa.orchestrator.gates import helpbox
    _ask(gates, "takeover")

    def locked(*a, **kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(helpbox.sqlite3, "connect", locked)
    r = gates.client.get(f"{gates.base}/assist")              # an empty list would close a take-over in the page
    assert r.status_code == 503 and r.json()["error"]["code"] == "busy"


def test_pause_reaches_a_command_line_run_and_a_finished_one_does_not_count(gates):
    from agentqa.orchestrator import live as live_runs
    folder = gates.project.state / "live" / "cli-20261105-100000-pipeline"
    folder.mkdir(parents=True)
    (folder / "running.json").write_text(json.dumps({"pid": 4242, "started": "2026-11-05T10:00:00"}), encoding="utf-8")
    (gates.project.state / "live" / "job-7-pipeline").mkdir()
    assert live_runs.cli_run_going(gates.project) is True
    assert gates.client.post(f"{gates.base}/pause", json={}, headers=CSRF).status_code == 200
    (folder / "running.json").write_text(json.dumps({"pid": 4242, "ended": "x"}), encoding="utf-8")
    assert live_runs.cli_run_going(gates.project) is False
