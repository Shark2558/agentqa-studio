"""Ask the tester: when an agent is stuck, it pauses on the live screen and asks a person.

Used for one-time passwords sent to a real phone, CAPTCHAs, "which button logs me in as a
citizen?", and any step the agent cannot work out alone. The question appears at once in every
open dashboard page (with the live screenshot, the buttons on screen, and a box to type into)
and in the terminal when AgentQA runs from a command prompt. The agent waits for the answer,
uses it, and remembers it (a login it was shown is recorded and replayed next time).

Kinds and their answers:
  otp, captcha, value   {"text": "482913"}
  navigate              {"option": 3} | {"x": 640, "y": 212} | {"text": "Citizen Login"} | {"takeover": true}
  confirm               {"ok": true} | {"option": 0}
  takeover              {"done": true} when the person has finished driving the browser
  any                   {"skip": true} when the person cannot help

Take over: the person drives the agent's browser until they press Continue. From the dashboard they click on the
live screenshot, type into the selected box (passwords and OTPs hidden) and press keys; when the browser window is
visible on this computer they can use it directly. Every click and value is recorded, so AgentQA repeats the path
next time (login_flow turns the recording into login steps and saves typed credentials, encrypted, on the Test data
page). The screenshot in the box is refreshed while the agent waits, so it always shows the screen as it is now.

Pause: the Pause button writes a flag; every agent checks it at its next step and hands that browser over.

Nothing typed stays readable (M1.4 decision 2, `assist_wipe`): a typed command keeps only its length once typed, and
is only ever echoed as its length; a secret answer becomes "[given]" once read; a question's screenshot is deleted
when it ends. Only the first answer counts, and a take-over that ends (or whose browser dies) is closed at once.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

from agentqa import live
from agentqa import assist_wipe as wipe
from agentqa.assist_recorder import recorder_flush, recorder_start
from agentqa.assist_screen import CLICKABLES_JS, Shooter, settle
from agentqa.assist_wipe import GIVEN, forget_typed
from agentqa.store import Store, now
from agentqa.util import log, warn

SECRET_AUTOCOMPLETE = ("one-time-code", "current-password", "new-password")


def _settings(project) -> dict:
    a = (project.cfg.get("assist") or {}) if project is not None else {}
    return {"enabled": a.get("enabled", True), "timeout_s": float(a.get("timeout_s", 600)),
            "terminal": a.get("terminal", True)}


def _open(project, db_path: Path | None, state_dir: Path | None) -> tuple[Store, Path]:
    folder = Path(state_dir or project.state) / "assist"
    folder.mkdir(parents=True, exist_ok=True)
    return Store(db_path or project.db_path), folder


def _detail(page, kind: str, options: list[str] | None, hint: str, secret: bool) -> dict:
    detail: dict = {"options": options or [], "hint": hint, "secret": secret}
    if page is not None:
        try:
            detail["url"] = page.url
            vp = page.viewport_size or {"width": 1280, "height": 800}
            detail["vw"], detail["vh"] = vp["width"], vp["height"]
            if kind == "navigate" and not options:
                detail["clickables"] = page.evaluate(CLICKABLES_JS)
        except Exception:  # noqa: BLE001
            pass
    return detail


def ask(project, kind: str, question: str, *, role: str | None = None, agent: str = "explorer", page=None,
        options: list[str] | None = None, hint: str = "", secret: bool = False, timeout: float | None = None,
        db_path: Path | None = None, state_dir: Path | None = None) -> dict | None:
    """Ask a person and wait. Returns the answer dict, or None when nobody answered in time or asking is off."""
    cfg = _settings(project)
    if not cfg["enabled"] or os.environ.get("AGENTQA_NO_ASSIST") == "1":
        warn(f"[{agent}] needs a person ({question}) but asking is switched off (assist.enabled)")
        return None
    store, folder = _open(project, db_path, state_dir)
    detail = _detail(page, kind, options, hint, secret)
    aid = store.insert("assist", {"at": now(), "kind": kind, "role": role, "agent": agent, "question": question,
                                  "detail": detail, "status": "pending", "answer": None, "answered_at": None})
    shooter = Shooter(page, folder, aid, store, detail) if page is not None else None
    if shooter:
        settle(page)
        shooter.refresh(force=True)
    live.emit(agent, "assist", f"Waiting for you: {question}", assist_id=aid, ask_kind=kind, role=role, level="warn")
    log(f"\n  >>> AgentQA needs you: {question}\n      Answer in the dashboard (a box opens on every page)"
        + (", or type it here and press Enter." if _tty(cfg) else "."))
    if _tty(cfg):
        threading.Thread(target=_read_terminal, args=(store.path, aid, kind), daemon=True).start()
    timeout_s = float(timeout or cfg["timeout_s"])
    try:
        return _await_answer(Store(store.path), aid, agent, page, shooter, time.time() + timeout_s, timeout_s, secret)
    finally:
        if shooter:
            shooter.close()


def _await_answer(poll: Store, aid: int, agent: str, page, shooter, limit: float, timeout_s: float,
                  secret: bool) -> dict | None:
    while time.time() < limit:
        row = poll.one("SELECT status, answer FROM assist WHERE id=?", [aid])
        if row and row["status"] != "pending":
            return _answered(poll, aid, agent, row, secret)
        if shooter:
            shooter.refresh()          # the screen may change while we wait (an OTP screen loading, a timer)
            page.wait_for_timeout(500)
        else:
            time.sleep(0.5)
    poll.exec("UPDATE assist SET status='expired' WHERE id=? AND status='pending'", [aid])
    row = poll.one("SELECT status, answer FROM assist WHERE id=?", [aid])
    if row and row["status"] == "answered":              # it came in the last moment: it still counts
        return _answered(poll, aid, agent, row, secret)
    live.emit(agent, "assist", f"Nobody answered within {int(timeout_s)} s; moving on", assist_id=aid, level="bad")
    return None


def _answered(poll: Store, aid: int, agent: str, row: dict, secret: bool) -> dict | None:
    ans = row["answer"] or {}
    if ans.get("skip"):
        live.emit(agent, "assist", "You chose to skip this step", assist_id=aid, level="warn")
        return None
    if secret and "text" in ans:
        wipe.overwrite(poll, "assist", aid, {"answer": {**ans, "text": GIVEN}})
        wipe.checkpoint(poll)
    live.emit(agent, "assist", "Thanks, continuing", assist_id=aid, level="ok")
    return ans


def _tty(cfg: dict) -> bool:
    try:
        return bool(cfg.get("terminal")) and sys.stdin is not None and sys.stdin.isatty() \
            and not os.environ.get("AGENTQA_LIVE_FROM_UI")
    except Exception:  # noqa: BLE001
        return False


def _read_terminal(db: Path, aid: int, kind: str) -> None:
    try:
        line = input("      > ").strip()
    except (EOFError, OSError):
        return
    s = Store(db)
    row = s.one("SELECT status FROM assist WHERE id=?", [aid])
    if row and row["status"] == "pending":
        ans = {"skip": True} if line.lower() in ("skip", "s", "") else (
            {"ok": line.lower() in ("y", "yes", "ok")} if kind == "confirm" else {"text": line})
        answer(s, aid, ans, via="terminal")


def answer(store: Store, aid: int, ans: dict, via: str = "dashboard") -> bool:
    """Record a person's answer; False when the question no longer waits. Only the first answer counts, even when
    two arrive at once (the check and the write are one step)."""
    cur = wipe.atomic(store, "UPDATE assist SET status='answered', answer=?, answered_at=? WHERE id=? AND status='pending'",
                      [json.dumps({**ans, "via": via}, ensure_ascii=False), now(), aid])
    return cur.rowcount == 1


def pending(store: Store) -> list[dict]:
    return store.all("SELECT * FROM assist WHERE status='pending' ORDER BY id")


def expire_stale(store: Store, older_than_s: float = 3600, shots: Path | None = None) -> None:
    """Questions left behind by a run that crashed, and anything typed that a run left readable (`assist_wipe.sweep`;
    `shots` is the screenshot folder, whose pictures of ended questions are deleted)."""
    cutoff = time.time() - older_than_s
    for r in store.all("SELECT id, at FROM assist WHERE status='pending'"):
        try:
            if time.mktime(time.strptime(r["at"], "%Y-%m-%dT%H:%M:%S")) < cutoff:
                store.exec("UPDATE assist SET status='expired' WHERE id=? AND status='pending'", [r["id"]])
        except ValueError:
            continue
    wipe.sweep(store, shots)


def dumps(rows: list[dict]) -> str:
    return json.dumps(rows, default=str)


# ---------------------------------------------------------------------------------------------
# take over: the person drives the browser, AgentQA records what they do

KEYS = {"Enter", "Tab", "Backspace", "Escape", "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Space"}

FOCUS_JS = r"""() => { const a = document.activeElement;
  if (!a || !(/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) || a.isContentEditable)) return false;
  return {box: true, password: String(a.type || '').toLowerCase() === 'password',
          autocomplete: String(a.getAttribute('autocomplete') || '').toLowerCase()}; }"""


def _type(page, cmd: dict) -> tuple[str, bool]:
    """Type into the focused box. Returns what was done, never the text itself (a one-time code typed into a plain box
    with "hide" not ticked must not be echoed either), and whether the box counts as secret."""
    text = str(cmd.get("text") or "")
    secret = bool(cmd.get("secret"))
    focus = page.evaluate(FOCUS_JS)
    if not isinstance(focus, dict) or not focus.get("box"):
        return "Nothing to type into: click a box on the screenshot first", secret
    secret = secret or bool(focus.get("password")) \
        or any(a in str(focus.get("autocomplete") or "") for a in SECRET_AUTOCOMPLETE)
    if cmd.get("replace"):
        page.keyboard.press("Control+A")
    page.keyboard.type(text, delay=15)
    return f"Typed {len(text)} character(s)", secret


def _run_cmd(page, cmd: dict, project=None) -> str:
    kind = cmd.get("kind")
    if kind == "click":
        x, y = float(cmd["x"]), float(cmd["y"])
        page.mouse.click(x, y)
        settle(page)
        return f"Clicked at ({int(x)}, {int(y)})"
    if kind == "type":
        return _type(page, cmd)[0]
    if kind == "press":
        key = str(cmd.get("key") or "")
        if key not in KEYS:
            return f"Key '{key}' is not allowed"
        page.keyboard.press(key)
        settle(page)
        return f"Pressed {key}"
    if kind == "back":
        page.go_back(wait_until="domcontentloaded")
        settle(page)
        return "Went back"
    if kind == "scroll":
        page.mouse.wheel(0, float(cmd.get("dy") or 400))
        page.wait_for_timeout(300)
        return "Scrolled"
    if kind == "goto":
        return _goto(page, str(cmd.get("path") or ""), project)
    return f"Unknown command {kind!r}"


def _goto(page, path: str, project) -> str:
    if project is None or not path.startswith(("/", "@")) or not project.in_scope(path):
        return f"'{path}' is outside the test scope"
    page.goto(project.url(path), wait_until="domcontentloaded")
    settle(page)
    events = getattr(page.context, "_aq_rec_events", None)
    if events is not None:              # an address typed in the dashboard is a step too (clicks record themselves)
        events.append({"kind": "goto", "path": path, "url": page.url, "t": time.time() * 1000})
    return f"Opened {path}"


def _run_queued(page, cmd: dict, project) -> tuple[str, str, dict | None]:
    """One queued command: what it did, "done" or "failed", and for typing the command as it is kept (no text)."""
    secret = None
    try:
        if cmd.get("kind") == "type":
            res, secret = _type(page, cmd)
        else:
            res = _run_cmd(page, cmd, project)
        ok = "done"
    except Exception as exc:  # noqa: BLE001
        res, ok = f"Could not do it: {exc.__class__.__name__}", "failed"
    return res, ok, (wipe.kept(cmd, secret) if cmd.get("kind") == "type" else None)


def _run_commands(poll: Store, page, aid: int, detail: dict, project, agent: str, role: str | None) -> bool:
    """Run the person's queued commands in order, stopping as soon as they press Continue or Cancel; True when any ran
    (the screenshot is then refreshed)."""
    cmds = poll.all("SELECT * FROM assist_cmds WHERE assist_id=? AND status='new' ORDER BY id", [aid])
    ran = typed = 0
    for c in cmds:
        if poll.scalar("SELECT status FROM assist WHERE id=?", [aid]) != "pending":
            break
        res, ok, kept = _run_queued(page, c["cmd"] if isinstance(c["cmd"], dict) else {}, project)
        if kept is None:
            poll.update("assist_cmds", "id", c["id"], {"status": ok, "result": res})
        else:
            wipe.overwrite(poll, "assist_cmds", c["id"], {"status": ok, "result": res, "cmd": kept})
            typed += 1
        detail["log"] = (detail.get("log") or [])[-11:] + [res]
        live.emit(agent, "action", f"You: {res}", role=role)
        ran += 1
    if typed:
        wipe.checkpoint(poll)
    return bool(ran)


def takeover(project, page, *, role: str | None = None, agent: str = "explorer", question: str = "", hint: str = "",
             timeout: float | None = None, db_path: Path | None = None, state_dir: Path | None = None) -> dict | None:
    """Hand this browser to a person until they press Continue. Returns {"done", "events", "url"}, or None when asking
    is off, they cancel, nobody comes in time, or the browser is gone."""
    cfg = _settings(project)
    if not cfg["enabled"] or os.environ.get("AGENTQA_NO_ASSIST") == "1":
        warn(f"[{agent}] would hand the browser to a person ({question}) but asking is switched off (assist.enabled)")
        return None
    store, folder = _open(project, db_path, state_dir)
    events = recorder_start(page)
    start_n = len(events)
    headed = os.environ.get("AGENTQA_HEADED") == "1"
    detail: dict = {"mode": "takeover", "hint": hint, "headed": headed, "log": []}
    aid = store.insert("assist", {"at": now(), "kind": "takeover", "role": role, "agent": agent,
                                  "question": question or "Take over the browser", "detail": detail,
                                  "status": "pending", "answer": None, "answered_at": None})
    shooter = Shooter(page, folder, aid, store, detail, every_s=1.2)
    settle(page)
    shooter.refresh(force=True)
    live.emit(agent, "assist", f"Waiting for you to take over: {question}", assist_id=aid, ask_kind="takeover", role=role,
              level="warn")
    log(f"\n  >>> AgentQA hands you the browser: {question}\n      Use the box in the dashboard"
        + (" or the browser window that opened" if headed else "") + ", then press Continue.")
    poll = Store(store.path)
    try:
        ans, timed_out = _drive(poll, page, aid, detail, shooter, project, agent, role,
                                time.time() + float(timeout or cfg["timeout_s"]))
    finally:
        _end_takeover(poll, aid, shooter)
    return _handed_back(project, page, aid, agent, ans, timed_out, events[start_n:])


def _drive(poll: Store, page, aid: int, detail: dict, shooter, project, agent: str, role: str | None,
           limit: float) -> tuple[dict | None, bool]:
    """Run the person's commands until they answer: (their answer, whether the time ran out). (None, False) when the
    browser is gone."""
    while time.time() < limit:
        row = poll.one("SELECT status, answer FROM assist WHERE id=?", [aid])
        if row and row["status"] != "pending":
            return row["answer"] or {}, False
        shooter.refresh(force=_run_commands(poll, page, aid, detail, project, agent, role))
        try:
            page.wait_for_timeout(300)        # keeps the browser (and the recorder's messages) flowing
        except Exception:  # noqa: BLE001
            return None, False
    return None, True


def _end_takeover(poll: Store, aid: int, shooter) -> None:
    """However the take-over ended, it no longer waits, nothing typed for it stays readable, and its screenshot goes."""
    try:
        poll.exec("UPDATE assist SET status='expired' WHERE id=? AND status='pending'", [aid])
        forget_typed(poll, aid)
    except sqlite3.Error as exc:
        warn(f"the take-over could not be closed yet ({exc.__class__.__name__}); the next sweep closes it")
    shooter.close()


def _handed_back(project, page, aid: int, agent: str, ans: dict | None, timed_out: bool, events: list) -> dict | None:
    if timed_out:
        live.emit(agent, "assist", "Nobody took over in time; moving on", assist_id=aid, level="bad")
        return None
    recorder_flush(page)
    if not ans or ans.get("skip"):
        live.emit(agent, "assist", "You cancelled the take-over" if ans else "The browser closed during the take-over",
                  assist_id=aid, level="warn")
        return None
    clear_pause(project)
    live.emit(agent, "assist", "Thanks, AgentQA continues from here", assist_id=aid, level="ok")
    return {"done": True, "events": list(events), "url": page.url, "assist_id": aid}


def add_command(store: Store, aid: int, cmd: dict, waiting_max: int | None = None) -> int:
    """Queue a command for a take-over that still waits; 0 when it no longer does (or `waiting_max` commands already
    wait). The check and the insert are one step, so two requests at once cannot pass it together."""
    limit = (" AND (SELECT COUNT(*) FROM assist_cmds WHERE assist_id=? AND status='new') < ?"
             if waiting_max is not None else "")
    cur = wipe.atomic(store, "INSERT INTO assist_cmds (assist_id, at, cmd, status, result) SELECT ?, ?, ?, 'new', NULL "
                             "WHERE EXISTS (SELECT 1 FROM assist WHERE id=? AND status='pending' AND kind='takeover')"
                             + limit, [aid, now(), json.dumps(cmd, ensure_ascii=False), aid,
                                       *([aid, waiting_max] if waiting_max is not None else [])])
    return cur.lastrowid if cur.rowcount == 1 else 0


# ---------------------------------------------------------------------------------------------
# pause: every agent hands its browser over at its next step

def _pause_file(project) -> Path:
    root = project if isinstance(project, (str, Path)) else project.state
    return Path(root) / "pause.flag"


def request_pause(project, by: str = "dashboard") -> None:
    _pause_file(project).write_text(json.dumps({"at": now(), "by": by}), encoding="utf-8")


def clear_pause(project) -> None:
    try:
        _pause_file(project).unlink(missing_ok=True)
    except (OSError, AttributeError):
        pass


def paused(project) -> bool:
    try:
        return _pause_file(project).exists()
    except AttributeError:
        return False


def checkpoint(project, page, *, role: str | None = None, agent: str = "explorer", where: str = "") -> dict | None:
    """Call between steps: when a pause was asked for, hand this browser over and wait for Continue."""
    if page is None or not paused(project):
        return None
    return takeover(project, page, role=role, agent=agent,
                    question=f"Paused{(' at ' + where) if where else ''}: you have control of the {role or 'agent'}'s browser",
                    hint="Click, type and press keys here (or in the browser window). Press Continue to let AgentQA go on "
                         "from this screen; what you did is recorded.")
