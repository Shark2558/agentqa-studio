"""M1.4 Phase C — the help box's engine (`agentqa.assist`), with a fake page instead of a browser.

The first group pins what the engine did before Phase C, so the new API can rely on it. The second is the hardening of
decision 2: nothing a person types (a password, a one-time code) stays readable in the project's database, which sits
in a folder that may be synced to the cloud, nor in a live recording."""
from __future__ import annotations

import json
import time

import pytest

from agentqa import assist, assist_wipe, live
from agentqa.store import Store
from assist_fakes import FakePage, file_bytes, in_thread, wait_until

MARKER = "Zq7-typed-secret-41"          # text no fixture or engine string contains


@pytest.fixture
def recording(tmp_path, monkeypatch):
    """Live events go to a recording folder of the test's own; returns a reader of everything written there."""
    folder = tmp_path / "live"
    monkeypatch.setattr(live, "_LIVE", live.Live(folder, "test"))

    def text() -> str:
        return "".join(f.read_text(encoding="utf-8") for f in folder.glob("*.jsonl"))
    return text


def _pending(s: Store, kind: str):
    return s.one("SELECT * FROM assist WHERE status='pending' AND kind=? ORDER BY id DESC LIMIT 1", [kind])


def _take_over(p, page, **kw):
    return in_thread(lambda: assist.takeover(p, page, role="citizen", agent="explorer", question="Log in for me",
                                             timeout=kw.get("timeout", 20)))


def _gone_from_file(path, text: str, seconds: float = 5.0) -> bool:
    """True once `text` is in neither the database file nor its log. The agent overwrites the row first and the
    checkpoint that empties the log follows (a second at most, see assist_wipe), so a test that reads the file at the
    moment the row looks wiped can catch the gap: a slow disk, like a hosted Windows runner's, does."""
    end = time.time() + seconds
    while time.time() < end:
        if text.encode() not in file_bytes(path):
            return True
        time.sleep(0.05)
    return text.encode() not in file_bytes(path)


def _done(s: Store, cid: int) -> dict:
    return wait_until(lambda: (lambda c: c if c and c["status"] != "new" else None)(
        s.one("SELECT * FROM assist_cmds WHERE id=?", [cid])))


# ---- what the engine does today (pinned before anything changes) ----------------------------------------------

def test_an_answer_counts_once(demo):
    _, s = demo
    aid = s.insert("assist", {"at": "2026-11-05T10:00:00", "kind": "otp", "role": "citizen", "agent": "explorer",
                              "question": "OTP?", "detail": {}, "status": "pending", "answer": None, "answered_at": None})
    assert assist.answer(s, aid, {"text": "1"}, via="app a@b (owner)") is True
    assert assist.answer(s, aid, {"text": "2"}) is False
    row = s.one("SELECT status, answer FROM assist WHERE id=?", [aid])
    assert row["status"] == "answered" and row["answer"] == {"text": "1", "via": "app a@b (owner)"}
    assert assist.answer(s, 999_999, {"ok": True}) is False


def test_commands_queue_only_for_a_pending_take_over(demo):
    _, s = demo
    base = {"at": "2026-11-05T10:00:00", "role": "citizen", "agent": "explorer", "question": "q", "detail": {},
            "answer": None, "answered_at": None}
    takeover = s.insert("assist", {**base, "kind": "takeover", "status": "pending"})
    question = s.insert("assist", {**base, "kind": "navigate", "status": "pending"})
    finished = s.insert("assist", {**base, "kind": "takeover", "status": "answered"})
    assert assist.add_command(s, takeover, {"kind": "back"}) > 0
    assert assist.add_command(s, question, {"kind": "back"}) == 0
    assert assist.add_command(s, finished, {"kind": "back"}) == 0
    assert assist.add_command(s, 999_999, {"kind": "back"}) == 0


def test_pause_records_who_and_clearing_it_resumes(demo):
    p, _ = demo
    assert not assist.paused(p)
    assist.request_pause(p, by="owner@example.com (owner)")
    assert assist.paused(p)
    flag = json.loads((p.state / "pause.flag").read_text(encoding="utf-8"))
    assert flag["by"] == "owner@example.com (owner)" and flag["at"]
    assist.clear_pause(p)
    assert not assist.paused(p)


def test_expire_stale_ends_questions_left_by_a_crashed_run_only(demo):
    _, s = demo
    old = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 7200))
    fresh = time.strftime("%Y-%m-%dT%H:%M:%S")
    row = {"kind": "otp", "role": "citizen", "agent": "explorer", "question": "q", "detail": {}, "status": "pending",
           "answer": None, "answered_at": None}
    stale = s.insert("assist", {**row, "at": old})
    current = s.insert("assist", {**row, "at": fresh})
    assist.expire_stale(s)
    states = {r["id"]: r["status"] for r in s.all("SELECT id, status FROM assist")}
    assert states == {stale: "expired", current: "pending"}


def test_commands_do_what_they_say_and_refuse_what_is_not_allowed(demo):
    p, _ = demo
    page = FakePage()
    assert assist._run_cmd(page, {"kind": "click", "x": 10.6, "y": 20}) == "Clicked at (10, 20)"
    assert page.mouse.clicks == [(10.6, 20.0)]
    assert assist._run_cmd(page, {"kind": "press", "key": "Enter"}) == "Pressed Enter"
    assert assist._run_cmd(page, {"kind": "press", "key": "F12"}) == "Key 'F12' is not allowed"
    assert page.keyboard.pressed == ["Enter"]
    assert assist._run_cmd(page, {"kind": "scroll", "dy": -300}) == "Scrolled" and page.mouse.wheel_dy == [-300.0]
    assert assist._run_cmd(page, {"kind": "back"}) == "Went back"
    assert assist._run_cmd(page, {"kind": "goto", "path": "/apply"}, p) == "Opened /apply"
    assert page.url == p.url("/apply")
    assert assist._run_cmd(page, {"kind": "goto", "path": "https://evil.example/"}, p).endswith("outside the test scope")
    assert assist._run_cmd(page, {"kind": "goto", "path": "/apply"}, None).endswith("outside the test scope")
    assert assist._run_cmd(page, {"kind": "wave"}) == "Unknown command 'wave'"


def test_typing_needs_a_box_and_what_is_typed_is_never_echoed(demo):
    page = FakePage(focus=None)
    assert assist._run_cmd(page, {"kind": "type", "text": "x"}).startswith("Nothing to type into")
    page.focus = "text"
    # a one-time code typed into a plain box with "hide" not ticked must not be echoed either (review, Phase C)
    assert assist._run_cmd(page, {"kind": "type", "text": "907315"}) == "Typed 6 character(s)"
    assert assist._run_cmd(page, {"kind": "type", "text": MARKER, "secret": True}) == f"Typed {len(MARKER)} character(s)"
    assert page.keyboard.typed == ["907315", MARKER]


def test_a_take_over_runs_the_queued_commands_until_the_person_hands_back(demo, recording):
    p, s = demo
    page = FakePage()
    thread, out = _take_over(p, page)
    aid = wait_until(lambda: _pending(s, "takeover"))["id"]
    cid = assist.add_command(s, aid, {"kind": "click", "x": 5, "y": 6})
    assert _done(s, cid)["result"] == "Clicked at (5, 6)"
    assert assist.answer(s, aid, {"done": True})
    thread.join(10)
    assert out["result"]["done"] is True and out["result"]["assist_id"] == aid
    assert "You: Clicked at (5, 6)" in recording()


# ---- decision 2: nothing typed stays readable ---------------------------------------------------------------

def test_typed_text_is_gone_from_the_row_and_the_database_file_once_it_ran(demo, recording, monkeypatch):
    real_checkpoint = assist_wipe.checkpoint

    def slow_disk(store):                  # the row is wiped first, the log emptied after: a slow disk widens the gap
        time.sleep(0.3)
        return real_checkpoint(store)
    monkeypatch.setattr(assist_wipe, "checkpoint", slow_disk)
    p, s = demo
    page = FakePage()
    thread, out = _take_over(p, page)
    aid = wait_until(lambda: _pending(s, "takeover"))["id"]
    secret = assist.add_command(s, aid, {"kind": "type", "text": MARKER, "secret": True, "replace": True})
    plain = assist.add_command(s, aid, {"kind": "type", "text": "9876543210"})
    _done(s, secret), _done(s, plain)
    rows = {r["id"]: r["cmd"] for r in s.all("SELECT id, cmd FROM assist_cmds")}
    assert rows[secret] == {"kind": "type", "chars": len(MARKER), "secret": True, "replace": True}
    assert rows[plain] == {"kind": "type", "chars": 10, "secret": False, "replace": False}
    assert page.keyboard.typed == [MARKER, "9876543210"]          # the agent typed the real text
    assert _gone_from_file(p.db_path, MARKER), "still readable in the database file or its log 5 s after it was typed"
    assert MARKER not in recording()
    assert assist.answer(s, aid, {"done": True})
    thread.join(10)
    assert out["result"]["done"] is True


def test_text_still_waiting_when_the_take_over_ends_is_wiped_too(demo):
    p, s = demo
    page = FakePage()
    thread, out = _take_over(p, page)
    aid = wait_until(lambda: _pending(s, "takeover"))["id"]
    s.conn.execute("BEGIN IMMEDIATE")                  # the command and the hand-back land together, so the agent
    s.conn.execute("INSERT INTO assist_cmds (assist_id, at, cmd, status) VALUES (?, ?, ?, 'new')",   # never runs it
                   [aid, "2026-11-05T10:00:00", json.dumps({"kind": "type", "text": MARKER, "secret": True})])
    s.conn.execute("UPDATE assist SET status='answered', answer=? WHERE id=?", [json.dumps({"done": True}), aid])
    s.conn.commit()
    thread.join(10)
    assert out["result"]["done"] is True
    assert all("text" not in r["cmd"] for r in s.all("SELECT cmd FROM assist_cmds"))
    assert MARKER.encode() not in file_bytes(p.db_path)


@pytest.mark.parametrize("focus", ["password", "otp"])
def test_typing_into_a_password_or_one_time_code_box_counts_as_secret(demo, recording, focus):
    p, s = demo
    page = FakePage(focus=focus)
    thread, _ = _take_over(p, page)
    aid = wait_until(lambda: _pending(s, "takeover"))["id"]
    cid = assist.add_command(s, aid, {"kind": "type", "text": MARKER})        # "hide" not ticked
    done = _done(s, cid)
    assert done["result"] == f"Typed {len(MARKER)} character(s)"
    assert done["cmd"]["secret"] is True
    log = s.one("SELECT detail FROM assist WHERE id=?", [aid])["detail"]["log"]
    assert all(MARKER not in line for line in log) and MARKER not in recording()
    assist.answer(s, aid, {"done": True})
    thread.join(10)


def test_a_secret_answer_is_overwritten_once_the_agent_has_read_it(demo):
    p, s = demo
    thread, out = in_thread(lambda: assist.ask(p, "otp", "Enter the OTP", role="citizen", agent="explorer",
                                               secret=True, timeout=20))
    aid = wait_until(lambda: _pending(s, "otp"))["id"]
    assert assist.answer(s, aid, {"text": "907315"}, via="app owner@example.com (owner)")
    thread.join(10)
    assert out["result"]["text"] == "907315"                      # the agent got the code
    row = s.one("SELECT status, answer FROM assist WHERE id=?", [aid])
    assert row["status"] == "answered"
    assert row["answer"] == {"text": "[given]", "via": "app owner@example.com (owner)"}
    assert b"907315" not in file_bytes(p.db_path)


def test_an_answer_that_is_not_secret_is_kept(demo):
    p, s = demo
    thread, out = in_thread(lambda: assist.ask(p, "navigate", "Which button?", role="citizen", timeout=20))
    aid = wait_until(lambda: _pending(s, "navigate"))["id"]
    assist.answer(s, aid, {"text": "Citizen Login"})
    thread.join(10)
    assert out["result"]["text"] == "Citizen Login"
    assert s.one("SELECT answer FROM assist WHERE id=?", [aid])["answer"]["text"] == "Citizen Login"


def test_the_sweep_wipes_what_a_crashed_agent_left_behind(demo):
    _, s = demo
    long_ago = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 7200))
    base = {"at": long_ago, "role": "citizen", "agent": "explorer", "question": "q"}
    otp = s.insert("assist", {**base, "kind": "otp", "detail": {"secret": True}, "status": "answered",
                              "answer": {"text": "907315", "via": "app"}, "answered_at": long_ago})
    takeover = s.insert("assist", {**base, "kind": "takeover", "detail": {}, "status": "pending", "answer": None,
                                   "answered_at": None})
    s.insert("assist_cmds", {"assist_id": takeover, "at": long_ago, "status": "new", "result": None,
                             "cmd": {"kind": "type", "text": MARKER, "secret": True}})
    assist.expire_stale(s)
    assert s.one("SELECT answer FROM assist WHERE id=?", [otp])["answer"]["text"] == "[given]"
    assert s.one("SELECT status FROM assist WHERE id=?", [takeover])["status"] == "expired"
    assert s.one("SELECT cmd FROM assist_cmds")["cmd"] == {"kind": "type", "chars": len(MARKER), "secret": True,
                                                            "replace": False}
    data = file_bytes(s.path)
    assert MARKER.encode() not in data and b"907315" not in data


# ---- review fixes (Phase C, fresh-context python and security reviews) ---------------------------------------

def test_a_take_over_whose_browser_dies_is_ended_and_its_typed_text_wiped(demo):
    p, s = demo
    page = FakePage()
    thread, out = _take_over(p, page)
    aid = wait_until(lambda: _pending(s, "takeover"))["id"]
    page.dead = True
    s.insert("assist_cmds", {"assist_id": aid, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "status": "new",
                             "result": None, "cmd": {"kind": "type", "text": MARKER, "secret": True}})
    thread.join(10)
    assert out["result"] is None
    assert s.one("SELECT status FROM assist WHERE id=?", [aid])["status"] == "expired"
    assert all("text" not in r["cmd"] for r in s.all("SELECT cmd FROM assist_cmds"))
    assert MARKER.encode() not in file_bytes(p.db_path)
    assert assist.add_command(s, aid, {"kind": "back"}) == 0


def test_an_answer_and_a_command_are_kept_only_while_the_question_waits(demo, monkeypatch):
    _, s = demo
    base = {"at": "2026-11-05T10:00:00", "role": "citizen", "agent": "explorer", "question": "q", "detail": {},
            "answer": None, "answered_at": None}
    aid = s.insert("assist", {**base, "kind": "otp", "status": "pending"})
    tid = s.insert("assist", {**base, "kind": "takeover", "status": "pending"})
    assert assist.answer(s, aid, {"text": "1"})
    s.exec("UPDATE assist SET status='answered' WHERE id=?", [tid])
    real_one = s.one
    monkeypatch.setattr(s, "one", lambda sql, params=(): ({"status": "pending", "kind": "takeover"}
                                                          if "FROM assist WHERE" in sql else real_one(sql, params)))
    assert assist.answer(s, aid, {"text": "2"}) is False            # the read raced: the write itself refuses
    assert assist.add_command(s, tid, {"kind": "type", "text": MARKER}) == 0
    monkeypatch.undo()
    assert s.one("SELECT answer FROM assist WHERE id=?", [aid])["answer"]["text"] == "1"
    assert s.scalar("SELECT COUNT(*) FROM assist_cmds") == 0


def test_cancel_stops_the_rest_of_a_queued_batch(demo):
    p, s = demo
    page = FakePage()
    aid = s.insert("assist", {"at": "2026-11-05T10:00:00", "kind": "takeover", "role": "citizen", "agent": "explorer",
                              "question": "q", "detail": {}, "status": "pending", "answer": None, "answered_at": None})
    first = assist.add_command(s, aid, {"kind": "click", "x": 1, "y": 1})
    second = assist.add_command(s, aid, {"kind": "click", "x": 2, "y": 2})
    page.mouse.click = lambda x, y: s.exec("UPDATE assist SET status='answered' WHERE id=?", [aid])   # Cancel
    assist._run_commands(Store(p.db_path), page, aid, {}, p, "explorer", "citizen")
    states = {r["id"]: r["status"] for r in s.all("SELECT id, status FROM assist_cmds")}
    assert states[first] == "done" and states[second] != "done"


def test_a_questions_screenshot_is_deleted_when_it_ends(demo):
    p, s = demo
    thread, _ = in_thread(lambda: assist.ask(p, "otp", "Enter the OTP", role="citizen", page=FakePage(), secret=True,
                                             timeout=20))
    row = wait_until(lambda: (lambda r: r if r and (r["detail"] or {}).get("shot") else None)(_pending(s, "otp")))
    shot = p.state / "assist" / row["detail"]["shot"]
    assert shot.is_file()
    assist.answer(s, row["id"], {"text": "907315"})
    thread.join(10)
    assert not shot.exists()
    page = FakePage()
    thread, _ = _take_over(p, page)
    row = wait_until(lambda: (lambda r: r if r and (r["detail"] or {}).get("shot") else None)(_pending(s, "takeover")))
    shot = p.state / "assist" / row["detail"]["shot"]
    assist.answer(s, row["id"], {"done": True})
    thread.join(10)
    assert not shot.exists()


def test_the_sweep_wipes_stale_commands_unread_answers_and_old_screenshots(demo):
    p, s = demo
    folder = p.state / "assist"
    folder.mkdir(parents=True, exist_ok=True)
    minutes_ago = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 300))
    base = {"at": minutes_ago, "role": "citizen", "agent": "explorer", "question": "q"}
    expired = s.insert("assist", {**base, "kind": "otp", "detail": {"secret": True}, "status": "expired",
                                  "answer": {"text": "907315", "via": "app"}, "answered_at": minutes_ago})
    waiting = s.insert("assist", {**base, "kind": "takeover", "detail": {"shot": "x"}, "status": "pending",
                                  "answer": None, "answered_at": None})
    s.insert("assist_cmds", {"assist_id": waiting, "at": minutes_ago, "status": "new", "result": None,
                             "cmd": {"kind": "type", "text": MARKER, "secret": True}})
    (folder / f"{expired}-3.jpg").write_bytes(b"old")
    (folder / f"{waiting}-1.jpg").write_bytes(b"current")
    assist.expire_stale(s, shots=folder)
    assert s.one("SELECT answer FROM assist WHERE id=?", [expired])["answer"]["text"] == "[given]"
    assert s.one("SELECT status FROM assist WHERE id=?", [waiting])["status"] == "pending"     # not an hour old
    assert s.one("SELECT cmd, status FROM assist_cmds") == {"cmd": {"kind": "type", "chars": len(MARKER), "secret": True,
                                                                   "replace": False}, "status": "dropped"}
    assert not (folder / f"{expired}-3.jpg").exists() and (folder / f"{waiting}-1.jpg").exists()
    data = file_bytes(p.db_path)
    assert MARKER.encode() not in data and b"907315" not in data


def test_a_wipe_does_not_hang_behind_a_reader_and_the_next_sweep_empties_the_log(demo):
    import sqlite3
    p, s = demo
    aid = s.insert("assist", {"at": "2026-11-05T10:00:00", "kind": "takeover", "role": "citizen", "agent": "explorer",
                              "question": "q", "detail": {}, "status": "answered", "answer": {"done": True},
                              "answered_at": "2026-11-05T10:00:00"})
    s.insert("assist_cmds", {"assist_id": aid, "at": "2026-11-05T10:00:00", "status": "done", "result": "Typed",
                             "cmd": {"kind": "type", "text": MARKER, "secret": True}})
    reader = sqlite3.connect(str(p.db_path))
    reader.execute("BEGIN")
    reader.execute("SELECT COUNT(*) FROM assist").fetchone()        # holds a snapshot: a full checkpoint must wait
    started = time.monotonic()
    assert assist.forget_typed(s, aid) == 1
    assert time.monotonic() - started < 5
    reader.rollback()
    reader.close()
    assist.expire_stale(s)
    assert MARKER.encode() not in file_bytes(p.db_path)
