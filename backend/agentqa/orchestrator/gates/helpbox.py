"""The help box, "AgentQA needs you" (M1.4 Phase C): what the agents wait for, a person's answers and take-over
commands, Pause and Resume. Every write says who; nothing a person typed is ever sent back.

Every open page polls the pending list (every 2 s), so it is one bare read-only query, like `jobs.peek`; the sweep for
questions a crashed run left behind (`assist.expire_stale`) runs at most once a minute per project. Text from the
tested site (the question's parts, the labels on screen, the address) is capped and sent as text only."""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from agentqa import assist
from agentqa.assist_wipe import SHOT_NAME
from agentqa.config import Project
from agentqa.orchestrator.gates import GateError, changelog, files, run_going
from agentqa.store import Store

log = logging.getLogger("agentqa.helpbox")

CAP = {"question": 500, "hint": 1000, "option": 200, "options": 20, "clickables": 40, "fields": 20, "log": 12,
       "line": 200, "url": 2000, "label": 200, "type": 40, "name": 80}
PENDING_MAX = 20
SWEEP_EVERY_S = 60
COMMANDS_WAITING_MAX = 20
PEEK_TIMEOUT_S = 2
VIEWPORT_MAX = 10_000
VERSION_MAX = 2 ** 31 - 1
DEFAULT_VIEWPORT = (1280, 800)
ANSWERS = {"takeover": {"done", "skip"}, "navigate": {"option", "point", "text", "takeover", "skip"},
           "confirm": {"option", "ok", "skip"}}         # the visual check asks "confirm" with two choices
OTHER_ANSWERS = {"text", "skip"}                     # otp, captcha, value and any kind added later
_SWEPT: dict[str, float] = {}
_SWEEP_LOCK = threading.Lock()


def _text(value: Any, cap: str) -> str:
    return value[:CAP[cap]] if isinstance(value, str) else ""


def _coord(value: Any) -> int | None:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    return int(value) if ok and 0 <= value <= VIEWPORT_MAX else None


def _version(value: Any) -> int:
    """The screenshot's version (it grows by one per new picture, so a long take-over passes any screen size)."""
    return value if type(value) is int and 0 <= value <= VERSION_MAX else 0


def _spots(raw: Any, cap: str, shape) -> list[dict]:
    """Things on the screen with a place to click (buttons, boxes); entries without one are dropped."""
    out = []
    for entry in raw if isinstance(raw, list) else []:
        spot = shape(entry) if isinstance(entry, dict) else None
        if spot and spot["x"] is not None and spot["y"] is not None:
            out.append(spot)
    return out[:CAP[cap]]


def _clickable(c: dict) -> dict:
    return {"text": _text(c.get("text"), "label"), "x": _coord(c.get("x")), "y": _coord(c.get("y"))}


def _field(f: dict) -> dict:
    return {"label": _text(f.get("label"), "label"), "type": _text(f.get("type"), "type"),
            "x": _coord(f.get("x")), "y": _coord(f.get("y")), "filled": bool(f.get("filled"))}


def _production(project: Project, role: str | None, url: str) -> bool:
    """Whether the screen belongs to a live production application (decision 6: a warning before taking over). When
    that cannot be read it counts as production: the warning then shows once too often, never once too few."""
    try:
        if url and project.is_internal(url):
            return project.is_production(project.rel(url))
        return project.is_production(project.app_of(role) if role else project.primary_app)
    except (KeyError, ValueError, AttributeError, TypeError):
        return True


def _viewport(detail: dict) -> tuple[int, int]:
    vw, vh = _coord(detail.get("vw")), _coord(detail.get("vh"))
    return (vw or DEFAULT_VIEWPORT[0], vh or DEFAULT_VIEWPORT[1])


def item(project: Project, row: dict, may_drive: bool) -> dict[str, Any]:
    """One waiting question. A person who may only watch gets who is waiting, never the screen or its parts."""
    base = {"id": row["id"], "kind": _text(row.get("kind"), "name"), "role": _text(row.get("role"), "name") or None,
            "agent": _text(row.get("agent"), "name"), "at": row.get("at")}
    if not may_drive:
        return base
    d = row.get("detail") if isinstance(row.get("detail"), dict) else {}
    url = _text(d.get("url"), "url")
    vw, vh = _viewport(d)
    options = d.get("options") if isinstance(d.get("options"), list) else []
    log = d.get("log") if isinstance(d.get("log"), list) else []
    return {**base, "question": _text(row.get("question"), "question"), "hint": _text(d.get("hint"), "hint"),
            "options": [_text(o, "option") for o in options[:CAP["options"]]],
            "clickables": _spots(d.get("clickables"), "clickables", _clickable),
            "fields": _spots(d.get("fields"), "fields", _field), "secret": bool(d.get("secret")), "url": url,
            "vw": vw, "vh": vh, "headed": bool(d.get("headed")),
            "log": [_text(line, "line") for line in log[-CAP["log"]:]],
            "shot_v": _version(d.get("shot_v")), "has_shot": bool(d.get("shot")),
            "production": _production(project, row.get("role"), url)}


def _decoded(detail: Any) -> dict:
    try:
        value = json.loads(detail) if isinstance(detail, str) else detail
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _peek(db_path: Path, where: str = "status='pending'", params: tuple = (), strict: bool = False) -> list[dict]:
    """The newest waiting questions, oldest first, from one bare read-only query (no schema set-up, no writes, so it
    never checkpoints or deletes the log files in a synced folder); [] when the project has no database yet. While
    the database cannot be read: [] (logged), or with `strict` a 503, so a page never mistakes "busy" for "nothing is
    waiting" and closes a take-over. `where` is always a literal from this module, never input."""
    if not db_path.is_file():
        return []
    try:
        with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=PEEK_TIMEOUT_S)) as conn:
            rows = conn.execute(f"SELECT id, at, kind, role, agent, question, detail FROM assist WHERE {where} "
                                "ORDER BY id DESC LIMIT ?", [*params, PENDING_MAX]).fetchall()
    except sqlite3.Error as exc:
        log.warning("the help box could not read %s now: %s", db_path.name, exc.__class__.__name__)
        if strict:
            raise GateError(503, "busy", "The help box could not be read just now; it tries again") from exc
        return []
    keys = ("id", "at", "kind", "role", "agent", "question", "detail")
    return [{**dict(zip(keys, r)), "detail": _decoded(r[6])} for r in reversed(rows)]


def _sweep(project: Project) -> None:
    """At most once a minute per project: what crashed runs left (`assist.expire_stale`). It never fails the list."""
    key = str(project.db_path)
    with _SWEEP_LOCK:
        if time.monotonic() - _SWEPT.get(key, -math.inf) < SWEEP_EVERY_S or not project.db_path.is_file():
            return
        _SWEPT[key] = time.monotonic()
    try:
        with closing(Store(project.db_path)) as s:
            assist.expire_stale(s, shots=project.state / "assist")
    except (sqlite3.Error, OSError) as exc:
        log.warning("the help box's sweep did not run now (%s); it runs again in a minute", exc.__class__.__name__)


def pause_state(project: Project) -> dict[str, Any]:
    flag = project.state / "pause.flag"
    if not flag.is_file():
        return {"on": False, "at": None, "by": None}
    try:
        data = json.loads(flag.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    return {"on": True, "at": _text(data.get("at"), "name") or None, "by": _text(data.get("by"), "label") or None}


def pending(project: Project, may_drive: bool) -> dict[str, Any]:
    items = [item(project, r, may_drive) for r in _peek(project.db_path, strict=True)]
    _sweep(project)
    return {"items": items, "paused": pause_state(project)}


def shot(project: Project, aid: int) -> files.SafeFile:
    """The current screenshot of a waiting question, by its id only (the name in the row must be the agent's own
    name for this very question)."""
    rows = _peek(project.db_path, "id=? AND status='pending'", (aid,))
    name = rows[0]["detail"].get("shot") if rows else None
    match = SHOT_NAME.fullmatch(name) if isinstance(name, str) else None
    plain = match is not None and int(match.group(1)) == aid
    found = files.safe_file(project, str(project.state / "assist" / name)) if plain else None
    if found is None or not found.inline:
        raise GateError(404, "not_found", "No screenshot for this question")
    return found


# ---- answers and commands -----------------------------------------------------------------------------------

def _row(store: Store, aid: int) -> dict:
    row = store.one("SELECT * FROM assist WHERE id=?", [aid])
    if not row:
        raise GateError(404, "not_found", "No such question")
    row["detail"] = row["detail"] if isinstance(row.get("detail"), dict) else {}
    return row


def _action(ans: dict) -> str:
    return "point" if "x" in ans else next(iter(ans))


def _check_answer(row: dict, action: str, ans: dict) -> None:
    allowed = ANSWERS.get(row["kind"], OTHER_ANSWERS)
    if action not in allowed:
        raise GateError(422, "validation", f"This question takes one of: {', '.join(sorted(allowed))}")
    options = row["detail"].get("options") or []
    if action == "option" and not ans["option"] < len(options):
        raise GateError(422, "validation", "option: no such choice")
    if action == "point":
        _inside(row["detail"], ans["x"], ans["y"])


def _inside(detail: dict, x: float, y: float) -> None:
    vw, vh = _viewport(detail)
    if not (0 <= x <= vw and 0 <= y <= vh):
        raise GateError(422, "validation", f"x, y: the point must be on the screen ({vw} x {vh})")


def _whose(row: dict) -> str:
    return f"the {_text(row.get('agent'), 'name') or 'agent'}'s"


def _said(row: dict, action: str, ans: dict) -> str:
    """The change log's words for an answer; a value a person typed is never written."""
    whose, kind = _whose(row), _text(row.get("kind"), "name")
    if action == "takeover":
        return f"asked to take over {whose} browser"
    if action == "done":
        return f"handed back {whose} browser"
    if action == "skip":
        return f"cancelled the take-over of {whose} browser" if kind == "takeover" else f"skipped {whose} {kind} question"
    shown = {"text": " (value hidden)", "ok": ": yes" if ans.get("ok") else ": no",
             "option": f": choice {int(ans.get('option') or 0) + 1}",
             "point": f": clicked at ({int(ans.get('x') or 0)}, {int(ans.get('y') or 0)})"}[action]
    return f"answered {whose} {kind} question{shown}"


def answer(store: Store, aid: int, ans: dict, by: str) -> dict[str, Any]:
    row = _row(store, aid)
    if row["status"] != "pending":
        raise GateError(409, "answered", "This question was already answered or is out of time")
    action = _action(ans)
    _check_answer(row, action, ans)
    if not assist.answer(store, aid, ans, via=f"app {by}"):
        raise GateError(409, "answered", "This question was already answered or is out of time")
    changelog.record(store, "assist", str(aid), _said(row, action, ans), "", by)
    return {"id": aid, "status": "answered"}


def _in_scope(project: Project, path: str) -> bool:
    """A path of the portal that stays a plain path once decoded (no `.` or `..` steps, no `//`, no backslash), and
    is in scope both as written and as the portal will read it."""
    decoded = unquote(path.split("?", 1)[0].split("#", 1)[0])
    steps = decoded.split("/")[1:]
    if "\\" in decoded or "//" in decoded or any(s in (".", "..") for s in steps):
        return False
    try:
        return path.startswith(("/", "@")) and project.in_scope(path) and project.in_scope(decoded)
    except (KeyError, ValueError, TypeError):
        return False


def command(project: Project, store: Store, aid: int, cmd: dict, by: str) -> dict[str, Any]:
    """Queue one take-over command for the agent's browser (the agent runs it within a second)."""
    row = _row(store, aid)
    if row["kind"] != "takeover" or row["status"] != "pending":
        raise GateError(409, "not_handed_over", "This browser is no longer handed over")
    if cmd["kind"] == "click":
        _inside(row["detail"], cmd["x"], cmd["y"])
    if cmd["kind"] == "goto" and not _in_scope(project, cmd["path"]):
        raise GateError(422, "validation", "path: that address is outside the test scope")
    first = not store.scalar("SELECT COUNT(*) FROM assist_cmds WHERE assist_id=?", [aid])
    cid = assist.add_command(store, aid, cmd, waiting_max=COMMANDS_WAITING_MAX)
    if not cid and store.scalar("SELECT status FROM assist WHERE id=?", [aid]) == "pending":
        raise GateError(429, "too_many", "Wait for the browser to catch up before sending more")
    if not cid:
        raise GateError(409, "not_handed_over", "This browser is no longer handed over")
    if first:
        role = _text(row.get("role"), "name")
        changelog.record(store, "assist", str(aid), f"took over {_whose(row)} browser" + (f" as {role}" if role else ""),
                         "", by)
    return {"id": cid}


# ---- pause and resume -----------------------------------------------------------------------------------------

def pause(project: Project, store: Store, by: str) -> dict[str, Any]:
    if not run_going(project, store):
        raise GateError(409, "not_running", "Nothing is running, so there is nothing to pause")
    assist.request_pause(project, by=by)
    changelog.record(store, "run", "-", "paused every agent", "", by)
    return pause_state(project)


def resume(project: Project, store: Store, by: str) -> dict[str, Any]:
    """Clear the pause (always: a flag left set would hand over the next run's browser) and hand back every
    browser still held, as Continue does."""
    was_paused = assist.paused(project)
    assist.clear_pause(project)
    handed = sum(assist.answer(store, r["id"], {"done": True}, via=f"app {by}")
                 for r in store.all("SELECT id FROM assist WHERE status='pending' AND kind='takeover'"))
    if was_paused or handed:
        changelog.record(store, "run", "-", "resumed" + (f" and handed back {handed} browser(s)" if handed else ""), "", by)
    return {**pause_state(project), "handed_back": handed}


def teach_role(project: Project, role: str) -> str:
    if role not in project.roles():
        raise GateError(422, "validation", "role: no such role in this project")
    return role
