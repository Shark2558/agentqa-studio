"""Logging in the way a manual tester does.

A tester opens the home page, looks for Login, picks the right kind of login (Citizen, Department,
Officer...), types what that login asks for (username and password, or a mobile number), presses
Get OTP or Sign in, types the OTP, and checks that they are in. This module does the same, on any
portal, without selectors in project.yaml:

  1. replay the steps recorded for the role the last time (fast, no guessing);
  2. otherwise read the screen and take the next sensible step, recording each one;
  3. when stuck, ask the local or Gemini model (if switched on), then ask you on screen:
     the live screenshot, the buttons it sees, and a box to type or click into.

OTPs come from the account's source: ask you (live portals: you read the SMS and type it),
the AgentQA mock inbox, a fixed test code, an authenticator secret, or a test API.
Sessions are saved per role and reused until they expire, so you are asked for an OTP once
per role per run, not once per test.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from agentqa import assist, language, live
from agentqa.config import Project
from agentqa.util import log, similarity, warn


class LoginError(RuntimeError):
    pass


SCAN_JS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none' && !e.closest('[hidden]'); };
  const txt = e => (e.innerText || e.value || e.getAttribute('aria-label') || e.title || '').trim().replace(/\s+/g, ' ');
  const labelOf = e => {
    let l = '';
    if (e.labels && e.labels.length) l = e.labels[0].innerText;
    if (!l && e.getAttribute('aria-label')) l = e.getAttribute('aria-label');
    if (!l && e.getAttribute('aria-labelledby')) l = e.getAttribute('aria-labelledby').split(/\s+/).map(i => (document.getElementById(i) || {}).innerText || '').join(' ');
    if (!l) { const g = e.closest('[role=group]'); if (g && g.getAttribute('aria-labelledby')) l = (document.getElementById(g.getAttribute('aria-labelledby')) || {}).innerText || ''; }
    if (!l) { let p = e.previousElementSibling; while (p && !l) { if (/^(LABEL|SPAN|DIV|P|B|STRONG)$/.test(p.tagName)) l = p.innerText; p = p.previousElementSibling; } }
    return (l || '').trim().replace(/\s+/g, ' ').slice(0, 80);
  };
  let n = 0; const inputs = [], clicks = [];
  for (const e of document.querySelectorAll('input, textarea, select')) {
    const type = (e.getAttribute('type') || e.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset', 'checkbox', 'radio', 'file'].includes(type)) continue;
    if (!vis(e) || e.disabled || e.readOnly) continue;
    const id = 'i' + (n++); e.setAttribute('data-aq-id', id);
    inputs.push({id, type, name: e.name || '', elid: e.id || '', label: labelOf(e), placeholder: e.placeholder || '',
                 autocomplete: e.autocomplete || '', inputmode: e.inputMode || '', maxlength: e.maxLength, filled: !!e.value});
  }
  const sel = 'a, button, [role=button], [role=tab], [role=menuitem], [role=link], input[type=submit], input[type=button], [onclick]';
  for (const e of document.querySelectorAll(sel)) {
    if (!vis(e) || e.disabled) continue;
    const t = txt(e); if (!t || t.length > 60) continue;
    const id = 'c' + (n++); e.setAttribute('data-aq-id', id);
    clicks.push({id, text: t, tag: e.tagName.toLowerCase(), href: e.getAttribute('href') || '', inForm: !!e.closest('form'),
                 submit: (e.tagName === 'BUTTON' && (e.getAttribute('type') || 'submit') === 'submit') || (e.tagName === 'INPUT' && e.type === 'submit')});
  }
  const alerts = [...document.querySelectorAll('[role=alert], .error, .alert-danger, .invalid-feedback, .text-danger, .error-message, .field-validation-error')]
    .filter(vis).map(txt).filter(Boolean).slice(0, 4);
  const captcha = !!document.querySelector('img[src*="captcha" i], img[alt*="captcha" i], [id*="captcha" i]:not(script), [name*="captcha" i], .g-recaptcha, iframe[src*="recaptcha"], iframe[src*="hcaptcha"]');
  return {url: location.href, title: document.title, inputs, clicks, alerts, captcha};
}"""

ENTRY = re.compile(r"^\s*(log\s?-?in|sign\s?-?in|login\s*/\s*(register|sign\s?up)|(user|portal|member)\s+log\s?in|log\s?in\s*here)\s*$", re.I)
ENTRY_LOOSE = re.compile(r"\b(log\s?-?in|sign\s?-?in)\b", re.I)
AVOID = re.compile(r"\b(register|sign\s?up|forgot|reset|resend|cancel|close|back|help|log\s?out|sign\s?out|faq|about|"
                   r"privacy|terms|contact|home|google|facebook|digilocker|aadhaar\s*(e-?kyc|otp))\b", re.I)
SEND_OTP = re.compile(r"\b(get|send|generate|request)\s*(the\s*)?otp\b", re.I)
SUBMIT = re.compile(r"\b(log\s?-?in|sign\s?-?in|submit|continue|next|proceed|go)\b", re.I)
VERIFY = re.compile(r"\b(verify|validate|confirm|submit|log\s?-?in|sign\s?-?in|continue|proceed)\b", re.I)
LOGOUT = re.compile(r"\b(log\s?-?out|sign\s?-?out)\b", re.I)
GENERIC_CHOICES = re.compile(r"\b(citizen|public|department|departmental|officer|official|staff|employee|admin|"
                             r"administrator|user|applicant|agency|organi[sz]ation|institution|partner)\b", re.I)


def _kind(i: dict) -> str:
    blob = " ".join(str(i.get(k) or "") for k in ("name", "elid", "label", "placeholder", "autocomplete")).lower()
    t = i.get("type") or ""
    if t == "select":
        return "choice"
    if t == "password" and not re.search(r"\botp\b", blob):
        return "password"
    if i.get("maxlength") == 1:
        return "otpbox"
    if re.search(r"captcha|security code|enter the (text|characters)|verification text", blob):
        return "captcha"
    if re.search(r"\botp\b|one[\s-]?time|one-time-code|verification code|passcode|\bpin\b|\bcode\b", blob):
        return "otp"
    if t == "email" or re.search(r"e-?mail", blob):
        return "email"
    if t == "tel" or re.search(r"mobile|phone|\bmob\b|contact\s*(no|number)|cell", blob):
        return "mobile"
    if re.search(r"user|login|log in|\bid\b|employee|emp\s*id|\bpen\b|staff|account|aadhaar|uid", blob):
        return "username"
    return "other"


def scan(page) -> dict:
    try:
        snap = page.evaluate(SCAN_JS)
    except Exception:  # noqa: BLE001
        page.wait_for_timeout(500)
        snap = page.evaluate(SCAN_JS)
    for i in snap["inputs"]:
        i["kind"] = _kind(i)
    # a lone text box next to a password box is the username
    if any(i["kind"] == "password" for i in snap["inputs"]):
        for i in snap["inputs"]:
            if i["kind"] == "other" and i["type"] in ("text", "input", ""):
                i["kind"] = "username"
                break
    snap["logout"] = any(LOGOUT.search(c["text"]) for c in snap["clicks"])
    return snap


def _desc(i: dict) -> dict:
    return {"kind": i["kind"], "name": i.get("name") or "", "label": i.get("label") or i.get("placeholder") or ""}


def _loc(page, item_id: str):
    return page.locator(f'[data-aq-id="{item_id}"]').first


def _account_value(project: Project, role: str, acc: dict, kind: str) -> str | None:
    if kind == "password":
        try:
            return project.role_password(role)
        except KeyError:
            return None
    if kind == "mobile":
        m = re.sub(r"\D", "", str(acc.get("mobile") or ""))
        return m[-10:] if len(m) >= 10 else (m or None)
    if kind == "email":
        return acc.get("email") or (acc.get("username") if "@" in str(acc.get("username") or "") else None)
    if kind == "username":
        return acc.get("username") or acc.get("email") or acc.get("mobile")
    if kind.startswith("extra:"):
        return _extras(acc).get(kind[6:])
    return None


def _extras(acc: dict) -> dict[str, str]:
    """Other login fields from the Test data page ('Department = Revenue', one per line)."""
    raw = acc.get("extra") or {}
    if isinstance(raw, str):
        raw = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    return {str(k).strip(): str(v).strip() for k, v in raw.items() if str(k).strip()}


def _fill_box(page, i: dict, value: str) -> None:
    loc = _loc(page, i["id"])
    if i.get("type") == "select":
        try:
            loc.select_option(label=value)
        except Exception:  # noqa: BLE001
            loc.select_option(value=value)
    else:
        loc.fill(value)


def _method(acc: dict) -> str:
    m = acc.get("method")
    if m == "mfa":
        return "password_otp"         # password, then a code from an authenticator app or SMS
    if m in ("sso", "custom"):
        return "password"             # the identity provider's page asks for a username and password
    if m:
        return m
    if acc.get("mobile") and not acc.get("username") and not acc.get("password") and not acc.get("password_env"):
        return "mobile_otp"
    return "password"


SCREENS_SEEN: dict[str, dict] = {}  # role -> {stage: what the login screens offered} (for functional test design)


_PROJECT_FOR_REL: list = []


def _rel(url: str) -> str:
    """Qualified path of a URL ('@department/login'), when a project is known; else the plain path."""
    if _PROJECT_FOR_REL:
        return _PROJECT_FOR_REL[-1].rel(url).split("?")[0]
    return urlparse(url).path


def _remember(role: str, stage: str, snap: dict) -> None:
    SCREENS_SEEN.setdefault(role, {})[stage] = {
        "path": _rel(snap["url"]), "clicks": [c["text"] for c in snap["clicks"]][:40],
        "inputs": [{**_desc(i), "maxlength": i.get("maxlength"), "type": i.get("type")} for i in snap["inputs"]][:20],
        "alerts": snap["alerts"][:3]}


OTP_OVERRIDE: dict[str, str] = {}   # role -> code to type instead (used by the OTP-reuse security check)
OTP_SEEN: dict[str, str] = {}       # role -> the last code typed


def otp_for(project: Project, role: str, page, since: float, agent: str) -> str:
    if role in OTP_OVERRIDE:
        return OTP_OVERRIDE[role]
    code = _otp_for(project, role, page, since, agent)
    OTP_SEEN[role] = code
    return code


def otp_source(project: Project, role: str) -> str:
    return project.account(role).get("otp_source") or ((project.cfg.get("login") or {}).get("otp") or {}).get("source") or "ask"


def _otp_for(project: Project, role: str, page, since: float, agent: str) -> str:
    from agentqa import inbox
    acc = project.account(role)
    source = acc.get("otp_source") or ((project.cfg.get("login") or {}).get("otp") or {}).get("source") or "ask"
    if source != "ask":
        return inbox.get_otp(project, role, since)
    where = acc.get("mobile") or acc.get("email") or "the registered mobile or email"
    ans = assist.ask(project, "otp", f"Enter the OTP the portal just sent to {_masked(where)} for {role}",
                     role=role, agent=agent, page=page, secret=True,
                     hint="Type the code you received. AgentQA types it into the portal and keeps the session, "
                          "so you are asked once per role per run.")
    code = re.sub(r"\D", "", str((ans or {}).get("text") or ""))
    if not code:
        raise LoginError(f"No OTP was given for {role}")
    return code


def _masked(v: str) -> str:
    v = str(v)
    digits = re.sub(r"\D", "", v)
    if "@" in v:
        name, _, dom = v.partition("@")
        return name[:2] + "***@" + dom
    return ("******" + digits[-4:]) if len(digits) >= 6 else v


def _fill_otp(page, snap: dict, code: str) -> dict:
    boxes = [i for i in snap["inputs"] if i["kind"] == "otpbox"]
    if len(boxes) >= 4:
        for i, b in enumerate(boxes):
            _loc(page, b["id"]).fill(code[i] if i < len(code) else "")
        return {"kind": "otpbox", "boxes": len(boxes)}
    field = next(i for i in snap["inputs"] if i["kind"] == "otp")
    _loc(page, field["id"]).fill(code)
    return _desc(field)


def _best_click(snap: dict, pattern: re.Pattern, avoid: re.Pattern | None = AVOID, prefer_submit: bool = False,
                skip: set | None = None) -> dict | None:
    cands = []
    for c in snap["clicks"]:
        if skip and c["text"].lower() in skip:
            continue
        if not pattern.search(c["text"]) or (avoid and avoid.search(c["text"]) and not pattern.search(c["text"].split()[0])):
            continue
        score = (2 if prefer_submit and c["submit"] else 0) + (1 if c["inForm"] else 0) - len(c["text"]) / 100
        cands.append((score, c))
    return max(cands, key=lambda x: x[0])[1] if cands else None


def _choice(snap: dict, acc: dict, role: str, aliases: list[str], skip: set) -> dict | None:
    """The login option for this role: 'Citizen Login', 'Department Login', an 'Officer' tab..."""
    want = [w for w in [acc.get("login_option")] if w] + aliases + [role]
    best, score = None, 0.0
    for c in snap["clicks"]:
        t = c["text"]
        if c["text"].lower() in skip or LOGOUT.search(t) or (AVOID.search(t) and not ENTRY_LOOSE.search(t)):
            continue
        for i, w in enumerate(want):
            w = str(w).strip()
            if not w:
                continue
            exact = t.lower() == w.lower()
            s = 1.0 if exact else (0.9 if w.lower() in t.lower() and len(t) < 40 else similarity(w, t))
            s -= 0.05 * min(i, 3)            # the configured login option beats a guess from the role name
            if s > score:
                best, score = c, s
    return best if score >= 0.72 else None


def logged_in(snap: dict, project: Project, identity_done: bool) -> bool:
    lg = project.login_cfg(project.split_path(project.rel(snap["url"]))[0]) if project.is_internal(snap["url"]) \
        else (project.cfg.get("login") or {})
    path = urlparse(snap["url"]).path
    if lg.get("success_url_contains") and lg["success_url_contains"] in snap["url"]:
        return True
    creds = any(i["kind"] in ("password", "otp", "otpbox", "mobile", "username", "email") for i in snap["inputs"])
    if snap["logout"] and not any(i["kind"] in ("otp", "otpbox", "password") for i in snap["inputs"]):
        return True
    marker = lg.get("success_url_not_contains")
    return bool(identity_done and not creds and not snap["alerts"] and not (marker and marker in path))


# ---------------------------------------------------------------------------------------------

class Recorder:
    def __init__(self):
        self.steps: list[dict] = []

    def add(self, step: dict) -> None:
        if "steps" in step:                     # what a person did while they had the browser
            self.steps.extend(step["steps"])
        else:
            self.steps.append(step)


def _css(v: str) -> str:
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _digits(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def steps_from_events(project: Project, role: str, events: list[dict]) -> tuple[list[dict], dict]:
    """A person's clicks and typing (recorded in the browser) as login steps. Values that match the role's account
    become tokens ({password}, {mobile}); login details we did not have are returned to be saved for the role;
    OTPs and CAPTCHAs become steps that ask again next time (they change every time)."""
    acc = project.account(role)
    known = {k: _account_value(project, role, acc, k) for k in ("password", "username", "mobile", "email")}
    steps: list[dict] = []
    learned: dict[str, str] = {}
    prev_box = False
    for ev in events:
        el = ev.get("el") or {}
        kind = ev.get("kind")
        if kind == "click":
            prev_box = False
            if el.get("tag") in ("input", "textarea", "select", "label") and el.get("type") not in ("submit", "button"):
                continue                                    # focusing a box: the typing step says it
            text = (el.get("text") or el.get("aria") or el.get("title") or "").strip()
            if text and len(text) <= 60:
                steps.append({"click": text})
            else:
                steps.append({"click_el": {k: el.get(k) for k in ("elid", "name", "aria", "title", "href", "tag") if el.get(k)},
                              "at": {"x": el.get("x"), "y": el.get("y")}})
            continue
        if kind in ("input", "select"):
            value = str(ev.get("value") or "")
            if not value:
                continue
            i = {"type": el.get("type") or ("select" if kind == "select" else "text"), "name": el.get("name") or "",
                 "elid": el.get("elid") or "", "label": el.get("label") or el.get("aria") or "",
                 "placeholder": el.get("placeholder") or "", "autocomplete": el.get("autocomplete") or "",
                 "maxlength": el.get("maxlength")}
            k = _kind(i)
            d = {"kind": k, "name": i["name"], "label": i["label"] or i["placeholder"]}
            if k == "otpbox":
                if not prev_box:
                    steps.append({"otp": d})
                prev_box = True
                continue
            prev_box = False
            if k == "otp":
                steps.append({"otp": d})
                continue
            if k == "captcha":
                steps.append({"captcha": d})
                continue
            order = [k] + [t for t in ("mobile", "email", "password", "username") if t != k]   # the box's own kind first
            token = next((t for t in order if known.get(t) and (value == str(known[t]) or (
                t == "mobile" and len(_digits(value)) >= 10 and _digits(value)[-10:] == _digits(known[t])[-10:]))), None)
            if token is None and k in ("password", "username", "mobile", "email"):
                token = k
                learned[k] = value                          # typed by the person: keep it for this role
            if steps and "fill" in steps[-1] and steps[-1]["fill"] == d:
                steps.pop()                                 # the same box typed twice: the last value counts
            steps.append({"fill": d, "value": "{" + token + "}" if token else value})
            continue
        if kind == "key" and ev.get("key") == "Enter":
            steps.append({"press": "Enter"})
    return steps, learned


def save_learned(project: Project, role: str, learned: dict) -> None:
    """Login details a person typed while driving the browser, kept (encrypted) on the Test data page."""
    if not learned:
        return
    try:
        project.vault.set_account(role, dict(learned))
        log(f"  [login] saved the {', '.join(sorted(learned))} you typed for {role} on the Test data page (encrypted)")
    except Exception as exc:  # noqa: BLE001
        warn(f"[login] could not save the details you typed for {role}: {exc}")


def _take_over(page, project: Project, role: str, agent: str, question: str, hint: str = "") -> dict | None:
    """Hand the browser to the person; their actions come back as steps (and typed login details are saved)."""
    res = assist.takeover(project, page, role=role, agent=agent, question=question, hint=hint or (
        "Do what a tester would do to log in: open the login, choose the right kind of login, type the username or mobile "
        "number and the password or OTP. Press Continue when you are in (or when AgentQA should carry on)."))
    if not res:
        return None
    steps, learned = steps_from_events(project, role, res["events"])
    save_learned(project, role, learned)
    live.emit(agent, "action", f"Recorded {len(steps)} step(s) you showed: " + " > ".join(_step_text(x) for x in steps[:8]),
              role=role)
    return {"steps": steps}


def _hint_key(project: Project, url: str) -> str:
    try:
        return project.rel(url).split("?")[0] or "/"
    except Exception:  # noqa: BLE001
        return urlparse(url).path or "/"


def _remember_hint(project: Project, role: str, url: str, step: dict) -> None:
    try:
        project.vault.add_login_hint(role, _hint_key(project, url), step.get("steps") or [step])
    except Exception as exc:  # noqa: BLE001
        warn(f"[login] could not keep what you showed for {role}: {exc}")


def _use_hint(page, project: Project, role: str, agent: str, snap: dict, used: set) -> dict | None:
    """A person showed what to do on this screen before: do it again instead of asking."""
    try:
        hints = project.vault.login_hints(role)
    except Exception:  # noqa: BLE001
        return None
    key = _hint_key(project, snap["url"])
    steps = hints.get(key)
    if not steps or key in used:
        return None
    first = steps[0]
    if "click" in first and not any(c["text"].lower() == first["click"].lower() for c in snap["clicks"]):
        return None
    used.add(key)
    live.emit(agent, "action", f"Doing what you showed me on {key} before", role=role)
    _replay_steps(page, project, role, steps, agent)
    return {"steps": steps}


def _wait(page) -> None:
    try:
        page.wait_for_load_state("load", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=2500)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(250)


def _click(page, c: dict, agent: str, role: str, why: str) -> None:
    loc = _loc(page, c["id"])
    live.shot(page, agent, "action", f"{why}: clicked '{c['text']}'", loc, role=role)
    loc.click(timeout=8000)
    _wait(page)


def _ask_next(page, project: Project, role: str, agent: str, snap: dict, goal: str,
              prefer: list[dict] | None = None, question: str | None = None) -> dict | None:
    """Stuck: ask the model (if any), then the person, what to do next. Returns a performed step or None."""
    step = _ask_model(page, project, role, agent, snap, goal)
    if step:
        return step
    cands = list(prefer or []) + [c for c in snap["clicks"] if c not in (prefer or [])]
    cands = cands[:30]
    opts = [c["text"] for c in cands]
    ans = assist.ask(project, "navigate", question or f"I am trying to {goal}. What should I click next?", role=role,
                     agent=agent, page=page, options=opts,
                     hint="Pick a button, click the place on the screenshot, or type the button's text. For more than "
                          "one step (typing a username, password or OTP), choose 'Let me take over the browser'. "
                          "AgentQA remembers it for next time.")
    if not ans:
        return None
    url = page.url
    step = _apply_answer(page, project, role, agent, snap, ans, cands, opts)
    if step:
        _remember_hint(project, role, url, step)
    return step


def _apply_answer(page, project: Project, role: str, agent: str, snap: dict, ans: dict, cands: list, opts: list) -> dict | None:
    if ans.get("takeover"):
        return _take_over(page, project, role, agent, f"Show AgentQA the way to log in as {role}")
    if "option" in ans and 0 <= int(ans["option"]) < len(opts):
        c = cands[int(ans["option"])]
        _click(page, c, agent, role, "As you showed me")
        return {"click": c["text"]}
    if "x" in ans and "y" in ans:
        x, y = float(ans["x"]), float(ans["y"])
        text = page.evaluate("([x, y]) => { const e = document.elementFromPoint(x, y); const t = e && (e.closest('a,button,[role=button],[role=tab],[role=menuitem],input,[onclick]') || e);"
                             " return t ? (t.innerText || t.value || t.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ').slice(0, 60) : ''; }", [x, y])
        live.emit(agent, "action", f"As you showed me: clicked at ({int(x)}, {int(y)})" + (f" '{text}'" if text else ""), role=role)
        page.mouse.click(x, y)
        _wait(page)
        return {"click": text} if text and len(text) < 50 else {"click_at": {"x": x, "y": y}}
    if ans.get("text"):
        t = ans["text"].strip()
        c = max(snap["clicks"], key=lambda c: similarity(t, c["text"]), default=None)
        if c and similarity(t, c["text"]) >= 0.7:
            _click(page, c, agent, role, "As you told me")
            return {"click": c["text"]}
        warn(f"[login] '{t}' does not match anything clickable on {snap['url']}")
    return None


def _ask_model(page, project: Project, role: str, agent: str, snap: dict, goal: str) -> dict | None:
    from agentqa.llm import get_llm
    llm = get_llm(project, "login")
    if not llm or not llm.available():
        return None
    view = {"url": snap["url"], "title": snap["title"],
            "fields": [{"id": i["id"], "kind": i["kind"], "label": i["label"] or i["placeholder"] or i["name"]} for i in snap["inputs"]],
            "buttons": [{"id": c["id"], "text": c["text"]} for c in snap["clicks"][:40]], "messages": snap["alerts"]}
    out = llm.chat_json("You are a careful manual software tester navigating a web portal. Reply with JSON only.",
                        f"Goal: {goal}.\nScreen: {json.dumps(view)}\n"
                        "Which ONE button should be clicked next to reach the login form for this kind of user? "
                        'Answer {"click": "<button id>", "reason": "..."} or {"click": null} if none fits.', 200)
    cid = (out or {}).get("click")
    c = next((c for c in snap["clicks"] if c["id"] == cid), None)
    if not c or AVOID.search(c["text"]) and not ENTRY_LOOSE.search(c["text"]):
        return None
    _click(page, c, agent, role, f"The model suggested it ({str(out.get('reason', ''))[:60]})")
    return {"click": c["text"]}


# ---------------------------------------------------------------------------------------------

def discover(page, project: Project, role: str, agent: str = "explorer") -> tuple[list[dict], bool]:
    """Find the way in by looking at the screen, like a tester. Returns (recorded steps, used an OTP)."""
    _PROJECT_FOR_REL[:] = [project]
    acc = project.account(role)
    method = _method(acc)
    aliases = [a for a in project.role_aliases().get(role, []) if a != role]
    start = project.login_start(role)
    goal = (f"log in as {role}" + (f" using '{acc['login_option']}'" if acc.get("login_option") else "")
            + {"mobile_otp": " with a mobile number and OTP", "email_otp": " with an email and OTP"}.get(method, ""))
    rec = Recorder()
    page.goto(project.url(start), wait_until="domcontentloaded")
    _wait(page)
    language.ensure_english(page, project, agent=agent, role=role)
    rec.add({"goto": start})
    live.shot(page, agent, "navigate", f"Looking for the way to {goal}", role=role, path=start)
    identity_done = used_otp = False
    since = time.time()
    clicked: dict[str, set] = {}
    states: dict[str, int] = {}
    otp_tries = 0
    hinted: set = set()

    def taught(step: dict | None) -> bool:
        nonlocal identity_done, used_otp
        if not step:
            return False
        rec.add(step)
        done = step.get("steps") or [step]
        identity_done = identity_done or any("fill" in x for x in done)
        used_otp = used_otp or any("otp" in x for x in done)
        return True
    for _ in range(16):
        if assist.paused(project) and taught(_take_over(page, project, role, agent,
                                                        f"Paused while looking for the {role} login: you have the browser")):
            continue
        snap = scan(page)
        if logged_in(snap, project, identity_done):
            live.shot(page, agent, "observe", f"Logged in as {role}" + (" with an OTP" if used_otp else ""), role=role,
                      path=urlparse(snap["url"]).path)
            return rec.steps, used_otp
        key = urlparse(snap["url"]).path + "|" + ",".join(sorted(i["kind"] for i in snap["inputs"])) + "|" + \
            ",".join(c["text"] for c in snap["clicks"][:25])
        states[key] = states.get(key, 0) + 1
        skip = clicked.setdefault(key, set())
        kinds = {i["kind"] for i in snap["inputs"]}
        if snap["alerts"] and identity_done and ({"password", "mobile", "username", "email"} & kinds) and not ({"otp", "otpbox"} & kinds):
            raise LoginError(f"The portal refused the login for {role}: {snap['alerts'][0]}")

        # 1. the OTP screen
        if identity_done and ({"otp", "otpbox"} & kinds) and states[key] <= 2:
            if snap["alerts"] and otp_tries:
                if otp_tries >= 2:
                    raise LoginError(f"The OTP was not accepted for {role}: {snap['alerts'][0]}")
            live.shot(page, agent, "observe", f"The portal asks {role} for a one-time password", role=role)
            _remember(role, "otp", snap)
            code = otp_for(project, role, page, since, agent)
            snap = scan(page)
            target = _fill_otp(page, snap, code)
            otp_tries += 1
            rec.add({"otp": target})
            live.shot(page, agent, "action", "Typed the OTP (hidden)", role=role)
            btn = _best_click(snap, VERIFY, prefer_submit=True)
            if btn:
                _click(page, btn, agent, role, "Submitted the OTP")
                rec.add({"click": btn["text"]})
            else:
                page.keyboard.press("Enter")
                _wait(page)
                rec.add({"press": "Enter"})
            used_otp = True
            continue

        # 2. the credential form
        ident_kind = {"mobile_otp": "mobile", "email_otp": "email"}.get(method)
        fields = [i for i in snap["inputs"] if i["kind"] in ("username", "password", "mobile", "email", "captcha")]
        wanted = [i for i in fields if (i["kind"] == ident_kind) or (ident_kind is None and i["kind"] in ("username", "password", "email"))
                  or i["kind"] == "captcha" or (i["kind"] == "password" and method in ("password", "password_otp"))]
        if not ident_kind and not any(i["kind"] == "password" for i in snap["inputs"]):
            wanted = [i for i in wanted if i["kind"] != "username"]    # a lone text box is not a login form
        if wanted and not (identity_done and states[key] > 2):
            _remember(role, "credentials", snap)
            for i in wanted:
                if i["kind"] == "captcha":
                    ans = assist.ask(project, "captcha", f"Type the CAPTCHA shown on the {role} login screen", role=role,
                                     agent=agent, page=page)
                    value = (ans or {}).get("text") or ""
                    rec.add({"captcha": _desc(i)})
                else:
                    value = _account_value(project, role, acc, i["kind"])
                    if value is None:
                        raise LoginError(f"The {role} login asks for a {i['kind']}, but the Test data page has none for "
                                         f"{role}. Add it there.")
                    rec.add({"fill": _desc(i), "value": "{" + i["kind"] + "}"})
                _loc(page, i["id"]).fill(str(value))
                live.shot(page, agent, "action", f"Typed the {i['kind']}" + (" (hidden)" if i["kind"] in ("password", "captcha")
                          else f" '{value}'"), _loc(page, i["id"]), role=role)
            # other fields this login needs (a department, a district, a user type...), from the Test data page
            for label, value in _extras(acc).items():
                box = max((x for x in snap["inputs"] if x not in wanted), default=None,
                          key=lambda x: similarity(label, x.get("label") or x.get("name") or x.get("placeholder")))
                if box and similarity(label, box.get("label") or box.get("name") or box.get("placeholder")) >= 0.75:
                    _fill_box(page, box, value)
                    rec.add({"fill": _desc(box), "value": "{extra:" + label + "}"})
                    live.shot(page, agent, "action", f"Chose '{value}' for {label}", _loc(page, box["id"]), role=role)
            btn = _best_click(snap, SEND_OTP, avoid=None) or _best_click(snap, SUBMIT, prefer_submit=True)
            since = time.time()
            if btn:
                _click(page, btn, agent, role, "Submitted the login form")
                rec.add({"click": btn["text"]})
            else:
                _loc(page, wanted[-1]["id"]).press("Enter")
                _wait(page)
                rec.add({"press": "Enter"})
            identity_done = True
            continue

        # 3. the right kind of login (Citizen / Department / an Officer tab ...)
        c = _choice(snap, acc, role, aliases, skip)
        if c and not (ENTRY.search(c["text"]) and not GENERIC_CHOICES.search(c["text"]) and not acc.get("login_option")):
            _remember(role, "choice", snap)
            skip.add(c["text"].lower())
            _click(page, c, agent, role, f"Chose the {role} login")
            rec.add({"click": c["text"]})
            continue
        # 4. several kinds of login on offer (Citizen, Department...) and none is clearly this role's: ask, don't guess
        offered, names = [], set()
        for c in snap["clicks"]:
            if ENTRY_LOOSE.search(c["text"]) and GENERIC_CHOICES.search(c["text"]) and c["text"].lower() not in skip \
                    and not LOGOUT.search(c["text"]) and c["text"].lower() not in names:
                names.add(c["text"].lower())
                offered.append(c)
        if len(offered) >= 2:
            if taught(_use_hint(page, project, role, agent, snap, hinted)):
                continue
            step = _ask_next(page, project, role, agent, snap, goal, prefer=offered,
                             question=f"Which login is for {role}? I see " + ", ".join(f"'{c['text']}'" for c in offered[:4])
                             + ". AgentQA will remember your choice (you can also set it as the role's login option on "
                               "the Test data page).")
            if not step:
                raise LoginError(f"The portal offers {', '.join(c['text'] for c in offered[:4])} and none is clearly for "
                                 f"{role}. Set the login option for {role} on the Test data page.")
            taught(step)
            continue
        # 5. the way in: a Login / Sign in button or link
        c = _best_click(snap, ENTRY, skip=skip) or _best_click(snap, ENTRY_LOOSE, skip=skip)
        if c:
            skip.add(c["text"].lower())
            _click(page, c, agent, role, "Opened the login")
            rec.add({"click": c["text"]})
            continue
        # 6. stuck: what a person showed here before, else ask (or let them take over)
        if taught(_use_hint(page, project, role, agent, snap, hinted)):
            continue
        step = _ask_next(page, project, role, agent, snap, goal)
        if not step:
            raise LoginError(f"Could not find how to {goal} on {snap['url']}. Show AgentQA the way when it asks, "
                             f"or use 'Show AgentQA how to log in' on the Test data page.")
        taught(step)
    raise LoginError(f"Gave up trying to {goal} after 16 steps")


def replay(page, project: Project, role: str, steps: list[dict], agent: str = "explorer") -> bool:
    """Repeat recorded login steps. Raises LoginError when the screen no longer matches them."""
    _PROJECT_FOR_REL[:] = [project]
    used_otp = _replay_steps(page, project, role, steps, agent, checkpoints=True)
    _wait(page)
    snap = scan(page)
    if not logged_in(snap, project, True):
        raise LoginError(f"The recorded login for {role} did not end logged in ({snap['url']}"
                         + (f": {snap['alerts'][0]}" if snap["alerts"] else "") + ")")
    return used_otp


class _TookOver(Exception):
    """A person took the browser during a replay and logged in themselves."""

    def __init__(self, used_otp: bool):
        super().__init__("taken over")
        self.used_otp = used_otp


def _replay_steps(page, project: Project, role: str, steps: list[dict], agent: str, checkpoints: bool = False) -> bool:
    acc = project.account(role)
    used_otp = False
    since = time.time()
    done: list[dict] = []
    for st in steps:
        if checkpoints and assist.paused(project):
            taught = _take_over(page, project, role, agent, f"Paused while logging in as {role}: you have the browser")
            if taught and logged_in(scan(page), project, True):
                new = done + taught["steps"]
                project.vault.set_login_steps(role, new)
                raise _TookOver(used_otp or any("otp" in x for x in taught["steps"]))
        done.append(st)
        if "goto" in st:
            page.goto(project.url(st["goto"]), wait_until="domcontentloaded")
            _wait(page)
            language.ensure_english(page, project, agent=agent, role=role)
            continue
        snap = scan(page)
        if "click" in st:
            want = st["click"].lower()
            c = next((c for c in snap["clicks"] if c["text"].lower() == want), None)
            if not c:
                page.wait_for_timeout(1200)
                snap = scan(page)
                c = next((c for c in snap["clicks"] if c["text"].lower() == want), None)
            if not c:
                raise LoginError(f"'{st['click']}' is no longer on {snap['url']}")
            since = time.time()
            _click(page, c, agent, role, "Login step")
        elif "click_el" in st:
            d = st["click_el"]
            sels = ([f"[id={_css(d['elid'])}]"] if d.get("elid") else []) + \
                ([f"[aria-label={_css(d['aria'])}]"] if d.get("aria") else []) + \
                ([f"[title={_css(d['title'])}]"] if d.get("title") else []) + \
                ([f"{d.get('tag') or '*'}[name={_css(d['name'])}]"] if d.get("name") else []) + \
                ([f"a[href={_css(d['href'])}]"] if d.get("href") else [])
            loc = next((page.locator(x).first for x in sels if page.locator(x).count()), None)
            since = time.time()
            if loc is not None:
                live.shot(page, agent, "action", "Login step: clicked where you showed me", loc, role=role)
                loc.click(timeout=8000)
            elif (st.get("at") or {}).get("x") is not None:
                page.mouse.click(float(st["at"]["x"]), float(st["at"]["y"]))
            else:
                raise LoginError(f"The control you showed is no longer on {snap['url']}")
            _wait(page)
        elif "click_at" in st:
            page.mouse.click(st["click_at"]["x"], st["click_at"]["y"])
            _wait(page)
        elif "press" in st:
            page.keyboard.press(st["press"])
            _wait(page)
        elif "fill" in st or "captcha" in st:
            d = st.get("fill") or st.get("captcha")
            if "credentials" not in SCREENS_SEEN.get(role, {}):
                _remember(role, "credentials", snap)
            i = _find_input(snap, d)
            if not i:
                raise LoginError(f"The {d.get('label') or d.get('kind')} box is no longer on {snap['url']}")
            if "captcha" in st:
                ans = assist.ask(project, "captcha", f"Type the CAPTCHA shown on the {role} login screen", role=role,
                                 agent=agent, page=page)
                value = (ans or {}).get("text") or ""
            elif re.fullmatch(r"\{[\w:]+\}", str(st.get("value") or "")):
                kind = st["value"].strip("{}")
                value = _account_value(project, role, acc, kind)
                if value is None:
                    raise LoginError(f"No {kind} for {role} on the Test data page")
            else:
                value = str(st.get("value") or "")        # a choice the person made (a district, a department)
            _fill_box(page, i, str(value))
            secret = d.get("kind") in ("password", "captcha")
            live.shot(page, agent, "action", f"Typed the {d.get('kind')}" + (" (hidden)" if secret else f" '{value}'"),
                      _loc(page, i["id"]), role=role)
        elif "otp" in st:
            for _ in range(10):
                if {"otp", "otpbox"} & {i["kind"] for i in snap["inputs"]}:
                    break
                page.wait_for_timeout(500)
                snap = scan(page)
            if not {"otp", "otpbox"} & {i["kind"] for i in snap["inputs"]}:
                # no OTP screen: the portal said why (wrong password...), so say that instead of waiting for an SMS
                if snap["alerts"]:
                    raise LoginError(f"The portal refused the login for {role}: {snap['alerts'][0]}")
                raise LoginError(f"The OTP screen did not appear for {role} on {snap['url']}")
            _remember(role, "otp", snap)
            code = otp_for(project, role, page, since, agent)
            snap = scan(page)
            try:
                _fill_otp(page, snap, code)
            except StopIteration as exc:
                raise LoginError(f"The OTP box is no longer on {snap['url']}") from exc
            used_otp = True
    return used_otp


def teach(page, project: Project, role: str, agent: str = "explorer") -> bool:
    """Show AgentQA how to log in: the person drives the browser from the start; the path and the details they type
    are saved, and the next login repeats them. True if an OTP was used."""
    _PROJECT_FOR_REL[:] = [project]
    start = project.login_start(role)
    page.goto(project.url(start), wait_until="domcontentloaded")
    _wait(page)
    language.ensure_english(page, project, agent=agent, role=role)
    taught = _take_over(page, project, role, agent, f"Show AgentQA how to log in as {role}",
                        hint=f"Log in as {role} the way you normally do: click through to the login, type the username or "
                             "mobile number, the password, and the OTP when it arrives. Press Continue when you see the "
                             "logged-in page. AgentQA saves the path and the details you type (encrypted).")
    if not taught:
        raise LoginError(f"Nobody showed AgentQA how to log in as {role}")
    _wait(page)
    if not logged_in(scan(page), project, True):
        raise LoginError(f"After your steps the {role} login did not end logged in ({page.url})")
    steps = [{"goto": start}] + taught["steps"]
    project.vault.set_login_steps(role, steps)
    log(f"  [login] learned {len(steps)} login step(s) for {role} from you: " + " > ".join(_step_text(x) for x in steps))
    return any("otp" in x for x in steps)


def _find_input(snap: dict, d: dict) -> dict | None:
    for i in snap["inputs"]:
        if d.get("name") and i.get("name") == d["name"]:
            return i
    for i in snap["inputs"]:
        if d.get("label") and similarity(d["label"], i.get("label") or i.get("placeholder")) >= 0.8:
            return i
    return next((i for i in snap["inputs"] if i["kind"] == d.get("kind")), None)


def _legacy(page, project: Project, role: str, agent: str) -> bool | None:
    """project.yaml login selectors (v0.1-v0.4 projects). None when they do not fit this portal."""
    lg = project.cfg.get("login") or {}
    acc = project.account(role)
    if not lg.get("username_selector") or acc.get("login_option") or _method(acc) not in ("password", "password_otp"):
        return None
    page.goto(project.url(lg.get("url") or "/login"), wait_until="domcontentloaded")
    if not page.locator(lg["username_selector"]).count() or not page.locator(lg["password_selector"]).count():
        return None
    page.fill(lg["username_selector"], str(acc.get("username") or ""))
    page.fill(lg["password_selector"], project.role_password(role))
    live.shot(page, agent, "action", "Typed the username and password (hidden)", page.locator(lg["username_selector"]).first, role=role)
    since = time.time()
    page.click(lg["submit_selector"])
    _wait(page)
    snap = scan(page)
    used = False
    if {"otp", "otpbox"} & {i["kind"] for i in snap["inputs"]}:
        code = otp_for(project, role, page, since, agent)
        _fill_otp(page, snap, code)
        btn = _best_click(snap, VERIFY, prefer_submit=True)
        (_click(page, btn, agent, role, "Submitted the OTP") if btn else page.keyboard.press("Enter"))
        _wait(page)
        used = True
    if not logged_in(scan(page), project, True):
        return None
    return used


def _auth_log(project: Project, role: str, result: str, detail: str, agent: str, secs: float) -> None:
    """Every login attempt is recorded (Test data page): OTP timeouts and refusals are never silent."""
    try:
        from agentqa.store import Store, now
        acc = project.account(role)
        app = acc.get("app") or project.app_of(role.split("__")[0])      # a second account logs in where its owner does
        Store(project.db_path).insert("auth_log", {"at": now(), "role": role, "app": app,
                                                   "method": _method(acc), "otp_source": otp_source(project, role),
                                                   "result": result, "detail": detail[:400], "agent": agent,
                                                   "seconds": round(secs, 1)})
    except Exception:  # noqa: BLE001
        pass


def login(page, project: Project, role: str, agent: str = "explorer") -> bool:
    """Log in as a role and record the attempt. True if an OTP was used."""
    started = time.time()
    try:
        used = _login(page, project, role, agent)
    except LoginError as exc:
        msg = str(exc)
        result = ("otp_timeout" if "No OTP was given" in msg else "otp_refused" if "OTP was not accepted" in msg
                  else "refused" if "refused" in msg else "not_found" if "Could not find" in msg or "Gave up" in msg
                  else "failed")
        _auth_log(project, role, result, msg, agent, time.time() - started)
        raise
    except Exception as exc:  # noqa: BLE001
        _auth_log(project, role, "error", f"{exc.__class__.__name__}: {exc}", agent, time.time() - started)
        raise
    _auth_log(project, role, "ok", ("logged in with an OTP" if used else "logged in") + f", landed on {project.rel(page.url).split('?')[0]}",
              agent, time.time() - started)
    return used


def _login(page, project: Project, role: str, agent: str = "explorer") -> bool:
    """Log in as a role: recorded steps, then project.yaml selectors, then a tester's search. True if an OTP was used."""
    if otp_source(project, role) == "inbox":
        from agentqa import inbox
        inbox.ensure(project)              # listening before the portal sends the SMS
    vault = project.vault
    steps = vault.login_steps(role) if vault.path.exists() else []
    if steps:
        try:
            used = replay(page, project, role, steps, agent)
            live.shot(page, agent, "observe", f"Logged in as {role} (recorded steps)", role=role,
                      path=urlparse(page.url).path)
            _save_screens(vault, role)
            return used
        except _TookOver as t:
            _save_screens(vault, role)
            return t.used_otp
        except LoginError as exc:
            warn(f"[login] recorded steps for {role} no longer work ({exc}); looking again")
    used = None
    if not steps:
        try:
            used = _legacy(page, project, role, agent)
        except Exception as exc:  # noqa: BLE001
            warn(f"[login] project.yaml login selectors did not work for {role} ({exc.__class__.__name__}); looking for the login")
            used = None
    if used is not None:
        return used
    found, used = discover(page, project, role, agent)
    try:
        vault.set_login_steps(role, found)
        _save_screens(vault, role)
        log(f"  [login] recorded {len(found)} login step(s) for {role}: "
            + " > ".join(_step_text(s) for s in found))
    except Exception as exc:  # noqa: BLE001
        warn(f"[login] could not save the login steps for {role}: {exc}")
    return used


def _save_screens(vault, role: str) -> None:
    seen = SCREENS_SEEN.get(role)
    if not seen:
        return
    try:
        if {**vault.login_screens(role), **seen} != vault.login_screens(role):
            vault.set_login_screens(role, {**vault.login_screens(role), **seen})
    except Exception as exc:  # noqa: BLE001
        warn(f"[login] could not save what the {role} login screens offer: {exc}")


def _step_text(s: dict) -> str:
    if "goto" in s:
        return f"open {s['goto']}"
    if "click" in s:
        return f"click '{s['click']}'"
    if "fill" in s:
        v = str(s.get("value") or "")
        what = v.strip("{}") if re.fullmatch(r"\{[\w:]+\}", v) else f"'{v}'"
        return f"type {what} in '{s['fill'].get('label') or s['fill'].get('kind')}'"
    if "otp" in s:
        return "type the OTP"
    if "captcha" in s:
        return "type the CAPTCHA"
    if "press" in s:
        return f"press {s['press']}"
    if "click_el" in s:
        d = s["click_el"]
        return f"click the control you showed ({d.get('aria') or d.get('title') or d.get('elid') or d.get('name') or d.get('tag')})"
    return "click on the screen"


def describe(steps: list[dict]) -> list[str]:
    return [_step_text(s) for s in steps]


# ---------------------------------------------------------------------------------------------
# sessions: log in once per role, reuse until it expires

def _meta_path(project: Project, role: str) -> Path:
    return project.state / "auth" / f"{role}.session.json"


def ensure_session(browser, project: Project, role: str, agent: str = "explorer", fresh: bool = False) -> Path:
    """A saved, working login for the role; logs in only when there is none or it stopped working."""
    path = project.auth_file(role)
    meta_p = _meta_path(project, role)
    # a saved session is used for as long as the portal still accepts it (checked by opening the landing page), so a
    # live portal does not ask for a new OTP on every run; session_minutes, when set, is an upper limit
    minutes = (project.cfg.get("login") or {}).get("session_minutes")
    max_age = float(minutes) * 60 if minutes else float("inf")
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    if not fresh and path.exists() and time.time() - float(meta.get("at", 0)) < max_age:
        ctx = browser.new_context(storage_state=str(path))
        page = ctx.new_page()
        try:
            page.goto(project.url(meta.get("landing") or "/"), wait_until="domcontentloaded")
            _wait(page)
            if logged_in(scan(page), project, False):
                live.emit(agent, "login", f"Reused the saved {role} session", role=role, level="ok")
                return path
        except Exception:  # noqa: BLE001
            pass
        finally:
            ctx.close()
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        used = login(page, project, role, agent)
        ctx.storage_state(path=str(path))
        meta_p.write_text(json.dumps({"at": time.time(), "landing": project.rel(page.url).split("?")[0] or "/", "otp": used}),
                          encoding="utf-8")
        return path
    finally:
        ctx.close()


def save_session(ctx, page, project: Project, role: str, used_otp: bool) -> Path:
    path = project.auth_file(role)
    ctx.storage_state(path=str(path))
    _meta_path(project, role).write_text(json.dumps({"at": time.time(), "landing": project.rel(page.url).split("?")[0] or "/",
                                                     "otp": used_otp}), encoding="utf-8")
    return path


def session_used_otp(project: Project, role: str) -> bool:
    p = _meta_path(project, role)
    return bool(p.exists() and json.loads(p.read_text(encoding="utf-8")).get("otp"))


def needs_person(project: Project, role: str) -> bool:
    """True when logging in as this role needs someone to type an OTP."""
    acc = project.account(role)
    source = acc.get("otp_source") or ((project.cfg.get("login") or {}).get("otp") or {}).get("source") or "ask"
    return source == "ask" and _method(acc) != "password"


def account_status(project: Project, role: str) -> dict:
    """Is this account ready to be used for testing (Active on the Test data page)? What exactly is missing if not."""
    import os as _os
    acc = project.account(role)
    m = _method(acc)
    src = otp_source(project, role)
    missing: list[str] = []
    has_pw = bool(acc.get("password") or _os.environ.get(acc.get("password_env") or "-"))
    if m in ("password", "password_otp", "mfa", "sso", "custom"):
        if not (acc.get("username") or acc.get("email") or acc.get("mobile")):
            missing.append("username")
        if m != "custom" and not has_pw:
            missing.append("password")
    if m in ("mobile_otp", "password_otp") and not acc.get("mobile"):
        missing.append("mobile number")
    if m == "email_otp" and not (acc.get("email") or "@" in str(acc.get("username") or "")):
        missing.append("email")
    if m in ("mobile_otp", "email_otp", "password_otp", "mfa"):
        if src == "fixed" and not acc.get("otp_fixed"):
            missing.append("the fixed test OTP")
        if src == "totp" and not acc.get("totp_secret"):
            missing.append("the authenticator secret")
    return {"ready": not missing, "missing": missing, "method": m, "otp_source": src}
