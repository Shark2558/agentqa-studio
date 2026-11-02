"""Ask the tester: when an agent is stuck, it pauses on the live screen and asks a person.

Used for one-time passwords sent to a real phone, CAPTCHAs, "which button logs me in as a
citizen?", and any step the agent cannot work out alone. The question appears at once in every
open dashboard page (with the live screenshot, the buttons on screen, and a box to type into)
and in the terminal when AgentQA runs from a command prompt. The agent waits for the answer,
uses it, and remembers it (a login it was shown is recorded and replayed next time).

Kinds and their answers:
  otp, captcha, value   {"text": "482913"}
  navigate              {"option": 3} | {"x": 640, "y": 212} | {"text": "Citizen Login"} | {"takeover": true}
  confirm               {"ok": true}
  takeover              {"done": true} when the person has finished driving the browser
  any                   {"skip": true} when the person cannot help

Take over: the person drives the agent's browser until they press Continue. From the dashboard they click on the
live screenshot, type into the selected box (passwords and OTPs hidden) and press keys; when the browser window is
visible on this computer they can use it directly. Every click and value is recorded, so AgentQA repeats the path
next time (login_flow turns the recording into login steps and saves typed credentials, encrypted, on the Test data
page). The screenshot in the box is refreshed while the agent waits, so it always shows the screen as it is now.

Pause: the Pause button writes a flag; every agent checks it at its next step and hands that browser over.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

from agentqa import live
from agentqa.store import Store, now
from agentqa.util import log, warn

CLICKABLES_JS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && s.display !== 'none' && r.bottom > 0 && r.top < innerHeight; };
  const out = [];
  for (const e of document.querySelectorAll('a[href], button, [role=button], [role=tab], [role=menuitem], [role=link], input[type=submit], input[type=button], [onclick]')) {
    if (!vis(e)) continue;
    const t = (e.innerText || e.value || e.getAttribute('aria-label') || e.title || '').trim().replace(/\s+/g, ' ');
    if (!t || t.length > 60) continue;
    const r = e.getBoundingClientRect();
    out.push({text: t, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)});
    if (out.length >= 40) break;
  }
  return out;
}"""


FIELDS_JS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && s.display !== 'none' && r.bottom > 0 && r.top < innerHeight; };
  const out = [];
  for (const e of document.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]), select, textarea')) {
    if (!vis(e) || e.disabled) continue;
    let l = (e.labels && e.labels.length ? e.labels[0].innerText : '') || e.getAttribute('aria-label') || e.placeholder || e.name || e.type;
    const r = e.getBoundingClientRect();
    out.push({label: (l || '').trim().replace(/\s+/g, ' ').slice(0, 40), type: e.type || e.tagName.toLowerCase(),
              x: Math.round(r.x + Math.min(r.width / 2, 60)), y: Math.round(r.y + r.height / 2), filled: !!e.value});
    if (out.length >= 20) break;
  }
  return out;
}"""


def _settings(project) -> dict:
    a = (project.cfg.get("assist") or {}) if project is not None else {}
    return {"enabled": a.get("enabled", True), "timeout_s": float(a.get("timeout_s", 600)),
            "terminal": a.get("terminal", True)}


def ask(project, kind: str, question: str, *, role: str | None = None, agent: str = "explorer", page=None,
        options: list[str] | None = None, hint: str = "", secret: bool = False, timeout: float | None = None,
        db_path: Path | None = None, state_dir: Path | None = None) -> dict | None:
    """Ask a person and wait. Returns the answer dict, or None when nobody answered in time or asking is off."""
    cfg = _settings(project)
    if not cfg["enabled"] or os.environ.get("AGENTQA_NO_ASSIST") == "1":
        warn(f"[{agent}] needs a person ({question}) but asking is switched off (assist.enabled)")
        return None
    store = Store(db_path or project.db_path)
    folder = Path(state_dir or project.state) / "assist"
    folder.mkdir(parents=True, exist_ok=True)
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
    aid = store.insert("assist", {"at": now(), "kind": kind, "role": role, "agent": agent, "question": question,
                                  "detail": detail, "status": "pending", "answer": None, "answered_at": None})
    shooter = _Shooter(page, folder, aid, store, detail) if page is not None else None
    if shooter:
        _settle(page)
        shooter.refresh(force=True)
    live.emit(agent, "assist", f"Waiting for you: {question}", assist_id=aid, ask_kind=kind, role=role, level="warn")
    log(f"\n  >>> AgentQA needs you: {question}\n      Answer in the dashboard (a box opens on every page)"
        + (", or type it here and press Enter." if _tty(cfg) else "."))
    if _tty(cfg):
        threading.Thread(target=_read_terminal, args=(store.path, aid, kind), daemon=True).start()
    limit = time.time() + float(timeout or cfg["timeout_s"])
    poll = Store(store.path)
    while time.time() < limit:
        row = poll.one("SELECT status, answer FROM assist WHERE id=?", [aid])
        if row and row["status"] != "pending":
            ans = row["answer"] or {}
            if ans.get("skip"):
                live.emit(agent, "assist", "You chose to skip this step", assist_id=aid, level="warn")
                return None
            live.emit(agent, "assist", "Thanks, continuing", assist_id=aid, level="ok")
            return ans
        if shooter:
            shooter.refresh()          # the screen may change while we wait (an OTP screen loading, a timer)
            page.wait_for_timeout(500)
        else:
            time.sleep(0.5)
    poll.update("assist", "id", aid, {"status": "expired"})
    live.emit(agent, "assist", f"Nobody answered within {int(timeout or cfg['timeout_s'])} s; moving on", assist_id=aid,
              level="bad")
    return None


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
    row = store.one("SELECT status FROM assist WHERE id=?", [aid])
    if not row or row["status"] != "pending":
        return False
    store.update("assist", "id", aid, {"status": "answered", "answer": {**ans, "via": via}, "answered_at": now()})
    return True


def pending(store: Store) -> list[dict]:
    rows = store.all("SELECT * FROM assist WHERE status='pending' ORDER BY id")
    for r in rows:
        if (r.get("detail") or {}).get("secret"):
            r["question"] = r["question"]
    return rows


def expire_stale(store: Store, older_than_s: float = 3600) -> None:
    """Questions left behind by a run that crashed."""
    cutoff = time.time() - older_than_s
    for r in store.all("SELECT id, at FROM assist WHERE status='pending'"):
        try:
            if time.mktime(time.strptime(r["at"], "%Y-%m-%dT%H:%M:%S")) < cutoff:
                store.update("assist", "id", r["id"], {"status": "expired"})
        except ValueError:
            continue


def dumps(rows: list[dict]) -> str:
    return json.dumps(rows, default=str)


# ---------------------------------------------------------------------------------------------
# live screenshots

def _settle(page) -> None:
    """Let the page finish what it is doing before it is shown to a person."""
    try:
        page.wait_for_load_state("load", timeout=5000)
        page.wait_for_load_state("networkidle", timeout=1500)
    except Exception:  # noqa: BLE001
        pass
    try:
        page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001
        pass


class _Shooter:
    """Keeps the screenshot of a question current: a new file (and version) whenever the screen changes."""

    def __init__(self, page, folder: Path, aid: int, store: Store, detail: dict, every_s: float = 1.5):
        self.page, self.folder, self.aid, self.store, self.detail, self.every = page, folder, aid, store, detail, every_s
        self.last_at, self.last_hash, self.v = 0.0, None, 0

    def refresh(self, force: bool = False) -> bool:
        if not force and time.time() - self.last_at < self.every:
            return False
        self.last_at = time.time()
        try:
            data = self.page.screenshot(type="jpeg", quality=70, timeout=5000)
        except Exception:  # noqa: BLE001
            return False
        h = hashlib.sha1(data).hexdigest()
        url = ""
        try:
            url = self.page.url
        except Exception:  # noqa: BLE001
            pass
        if h == self.last_hash and url == self.detail.get("url") and not force:
            return False
        self.last_hash, self.v = h, self.v + 1
        name = f"{self.aid}-{self.v}.jpg"
        (self.folder / name).write_bytes(data)
        old = self.detail.get("shot")
        self.detail.update(shot=name, shot_v=self.v, url=url)
        try:
            vp = self.page.viewport_size or {"width": 1280, "height": 800}
            self.detail["vw"], self.detail["vh"] = vp["width"], vp["height"]
            if not self.detail.get("options"):
                self.detail["clickables"] = self.page.evaluate(CLICKABLES_JS)
            if self.detail.get("mode") == "takeover":
                self.detail["fields"] = self.page.evaluate(FIELDS_JS)
        except Exception:  # noqa: BLE001
            pass
        self.store.update("assist", "id", self.aid, {"detail": self.detail})
        if old and old != name:
            try:
                (self.folder / old).unlink(missing_ok=True)
            except OSError:
                pass
        return True


# ---------------------------------------------------------------------------------------------
# take over: the person drives the browser, AgentQA records what they do

RECORDER_JS = r"""(() => {
  if (window.__aqRecOn) return; window.__aqRecOn = true;
  const send = ev => { try { if (window.__aqRec) window.__aqRec(ev); } catch (e) {} };
  const clean = t => (t || '').trim().replace(/\s+/g, ' ');
  const labelOf = e => {
    let l = '';
    if (e.labels && e.labels.length) l = e.labels[0].innerText;
    if (!l && e.getAttribute && e.getAttribute('aria-label')) l = e.getAttribute('aria-label');
    if (!l) { let p = e.previousElementSibling; while (p && !l) { if (/^(LABEL|SPAN|DIV|P|B|STRONG)$/.test(p.tagName)) l = p.innerText; p = p.previousElementSibling; } }
    return clean(l).slice(0, 80);
  };
  const desc = e => {
    if (!e || !e.tagName) return {};
    const d = {tag: e.tagName.toLowerCase(), type: (e.getAttribute('type') || (e.tagName === 'SELECT' ? 'select' : e.tagName === 'TEXTAREA' ? 'textarea' : '')).toLowerCase(),
               name: e.name || e.getAttribute('name') || '', elid: e.id || '', label: /^(INPUT|SELECT|TEXTAREA)$/.test(e.tagName) ? labelOf(e) : '',
               placeholder: e.placeholder || '', aria: e.getAttribute('aria-label') || '', title: e.title || '',
               text: /^(INPUT|SELECT|TEXTAREA)$/.test(e.tagName) ? clean(e.type === 'submit' || e.type === 'button' ? e.value : '') : clean(e.innerText).slice(0, 80),
               href: e.getAttribute('href') || '', autocomplete: e.autocomplete || '', maxlength: e.maxLength > 0 ? e.maxLength : null,
               role: e.getAttribute('role') || ''};
    return d;
  };
  const target = e => (e && e.closest) ? (e.closest('a,button,[role=button],[role=tab],[role=menuitem],[role=link],input,select,textarea,summary,label,[onclick]') || e) : e;
  const last = new WeakMap();
  const flush = e => {
    if (!e || !/^(INPUT|SELECT|TEXTAREA)$/.test(e.tagName) || ['submit', 'button', 'checkbox', 'radio', 'file', 'hidden'].includes(e.type)) return;
    const v = e.tagName === 'SELECT' ? clean((e.options[e.selectedIndex] || {}).text || e.value) : e.value;
    if (last.get(e) === v) return; last.set(e, v);
    send({kind: e.tagName === 'SELECT' ? 'select' : 'input', el: desc(e), value: v, url: location.href, t: Date.now()});
  };
  document.addEventListener('click', ev => { const t = target(ev.target);
    if (t && /^(INPUT|TEXTAREA)$/.test(t.tagName) && !['submit', 'button', 'checkbox', 'radio'].includes(t.type)) return;
    send({kind: 'click', el: Object.assign(desc(t), {x: ev.clientX, y: ev.clientY}), url: location.href, t: Date.now()}); }, true);
  document.addEventListener('change', ev => flush(ev.target), true);
  document.addEventListener('blur', ev => flush(ev.target), true);
  document.addEventListener('keydown', ev => { if (ev.key === 'Enter') { flush(ev.target); send({kind: 'key', key: 'Enter', el: desc(ev.target), url: location.href, t: Date.now()}); } }, true);
  document.addEventListener('submit', ev => { for (const e of ev.target.querySelectorAll('input,select,textarea')) flush(e); }, true);
  window.addEventListener('pagehide', () => flush(document.activeElement), true);
})();"""


def recorder_start(page) -> list[dict]:
    """Record what is done in this browser (clicks, typed values, Enter). Returns the live list of events."""
    ctx = page.context
    events = getattr(ctx, "_aq_rec_events", None)
    if events is None:
        events = []
        ctx._aq_rec_events = events

        def on_event(_source, ev):
            ctx._aq_rec_events.append(ev)
        ctx.expose_binding("__aqRec", on_event)
        ctx.add_init_script(RECORDER_JS)
    try:
        page.evaluate(RECORDER_JS)
    except Exception:  # noqa: BLE001
        pass
    return events


def recorder_flush(page) -> None:
    try:
        page.evaluate("() => { const a = document.activeElement; if (a && a.blur) a.blur(); }")
        page.wait_for_timeout(150)
    except Exception:  # noqa: BLE001
        pass


KEYS = {"Enter", "Tab", "Backspace", "Escape", "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Space"}


def _run_cmd(page, cmd: dict, project=None) -> str:
    kind = cmd.get("kind")
    if kind == "click":
        x, y = float(cmd["x"]), float(cmd["y"])
        page.mouse.click(x, y)
        _settle(page)
        return f"Clicked at ({int(x)}, {int(y)})"
    if kind == "type":
        text = str(cmd.get("text") or "")
        focused = page.evaluate("() => { const a = document.activeElement; return !!a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) || (a && a.isContentEditable); }")
        if not focused:
            return "Nothing to type into: click a box on the screenshot first"
        if cmd.get("replace"):
            page.keyboard.press("Control+A")
        page.keyboard.type(text, delay=15)
        return f"Typed {len(text)} character(s)" if cmd.get("secret") else f"Typed '{text[:40]}'"
    if kind == "press":
        key = str(cmd.get("key") or "")
        if key not in KEYS:
            return f"Key '{key}' is not allowed"
        page.keyboard.press(key)
        _settle(page)
        return f"Pressed {key}"
    if kind == "back":
        page.go_back(wait_until="domcontentloaded")
        _settle(page)
        return "Went back"
    if kind == "scroll":
        page.mouse.wheel(0, float(cmd.get("dy") or 400))
        page.wait_for_timeout(300)
        return "Scrolled"
    if kind == "goto":
        path = str(cmd.get("path") or "")
        if project is None or not path.startswith(("/", "@")) or not project.in_scope(path):
            return f"'{path}' is outside the test scope"
        page.goto(project.url(path), wait_until="domcontentloaded")
        _settle(page)
        events = getattr(page.context, "_aq_rec_events", None)
        if events is not None:              # an address typed in the dashboard is a step too (clicks record themselves)
            events.append({"kind": "goto", "path": path, "url": page.url, "t": time.time() * 1000})
        return f"Opened {path}"
    return f"Unknown command {kind!r}"


def takeover(project, page, *, role: str | None = None, agent: str = "explorer", question: str = "", hint: str = "",
             timeout: float | None = None, db_path: Path | None = None, state_dir: Path | None = None) -> dict | None:
    """Hand this browser to a person until they press Continue. Returns {"done", "events", "url"}, or None when asking
    is off, they cancel, or nobody comes in time."""
    cfg = _settings(project)
    if not cfg["enabled"] or os.environ.get("AGENTQA_NO_ASSIST") == "1":
        warn(f"[{agent}] would hand the browser to a person ({question}) but asking is switched off (assist.enabled)")
        return None
    store = Store(db_path or project.db_path)
    folder = Path(state_dir or project.state) / "assist"
    folder.mkdir(parents=True, exist_ok=True)
    events = recorder_start(page)
    start_n = len(events)
    headed = os.environ.get("AGENTQA_HEADED") == "1"
    detail: dict = {"mode": "takeover", "hint": hint, "headed": headed, "log": []}
    aid = store.insert("assist", {"at": now(), "kind": "takeover", "role": role, "agent": agent,
                                  "question": question or "Take over the browser", "detail": detail,
                                  "status": "pending", "answer": None, "answered_at": None})
    shooter = _Shooter(page, folder, aid, store, detail, every_s=1.2)
    _settle(page)
    shooter.refresh(force=True)
    live.emit(agent, "assist", f"Waiting for you to take over: {question}", assist_id=aid, ask_kind="takeover", role=role,
              level="warn")
    log(f"\n  >>> AgentQA hands you the browser: {question}\n      Use the box in the dashboard"
        + (" or the browser window that opened" if headed else "") + ", then press Continue.")
    limit = time.time() + float(timeout or cfg["timeout_s"])
    poll = Store(store.path)
    ans = None
    while time.time() < limit:
        row = poll.one("SELECT status, answer FROM assist WHERE id=?", [aid])
        if row and row["status"] != "pending":
            ans = row["answer"] or {}
            break
        cmds = poll.all("SELECT * FROM assist_cmds WHERE assist_id=? AND status='new' ORDER BY id", [aid])
        for c in cmds:
            try:
                res = _run_cmd(page, c["cmd"] or {}, project)
                ok = "done"
            except Exception as exc:  # noqa: BLE001
                res, ok = f"Could not do it: {exc.__class__.__name__}", "failed"
            poll.update("assist_cmds", "id", c["id"], {"status": ok, "result": res})
            detail["log"] = (detail.get("log") or [])[-11:] + [res]
            live.emit(agent, "action", f"You: {res}", role=role)
        if cmds:
            shooter.refresh(force=True)
        else:
            shooter.refresh()
        try:
            page.wait_for_timeout(300)        # keeps the browser (and the recorder's messages) flowing
        except Exception:  # noqa: BLE001
            break
    else:
        poll.update("assist", "id", aid, {"status": "expired"})
        live.emit(agent, "assist", "Nobody took over in time; moving on", assist_id=aid, level="bad")
        return None
    recorder_flush(page)
    if not ans or ans.get("skip"):
        live.emit(agent, "assist", "You cancelled the take-over", assist_id=aid, level="warn")
        return None
    clear_pause(project)
    live.emit(agent, "assist", "Thanks, AgentQA continues from here", assist_id=aid, level="ok")
    return {"done": True, "events": list(events[start_n:]), "url": page.url, "assist_id": aid}


def add_command(store: Store, aid: int, cmd: dict) -> int:
    row = store.one("SELECT status, kind FROM assist WHERE id=?", [aid])
    if not row or row["status"] != "pending" or row["kind"] != "takeover":
        return 0
    return store.insert("assist_cmds", {"assist_id": aid, "at": now(), "cmd": cmd, "status": "new", "result": None})


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
