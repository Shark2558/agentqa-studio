"""Visual QA agent: carries out a test step nobody recorded, and judges an expected result, from what is on screen.

Recorded steps (goto, click 'Apply', fill 'mobile') run without a model. A case drafted from a requirement can
also hold *intent* steps ("Open My Applications and pick the latest one") and *verify* steps ("the status shows
Verified"). For those the Visual QA agent looks at the page the way a tester does:

  sees     the visible text, every visible control (numbered), the accessibility tree, and a screenshot when the
           project's consent allows images to be sent and the model can see (off by default)
  acts     one action at a time on a control it was shown (never a made-up selector); values only from the
           test data tokens ({mobile}, {name}...) or plain sample text, so it never sees a password; nothing
           that changes data on a production application
  judges   a Pass needs words copied from the page that prove it: a quote that is not on the page makes the
           verdict "not verified", never Passed
  asks     a person (the live assist box) when there is no model, the model is stuck or unsure, and asking is on

Without a model and without a person the step is NOT RUN, with the reason. It is never skipped silently.
"""
from __future__ import annotations

import json
import re
import time

from agentqa.util import warn

MARK = "data-aq-i"
ELEMENTS_JS = r"""(mark) => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const label = e => { if (e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); if (l) return l.innerText; }
    const p = e.closest('label'); return p ? p.innerText : ''; };
  const out = []; let i = 0;
  document.querySelectorAll('[' + mark + ']').forEach(e => e.removeAttribute(mark));
  for (const e of document.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], [role=tab], [role=menuitem], [onclick]')) {
    if (!vis(e) || e.disabled) continue;
    i += 1; e.setAttribute(mark, String(i));
    const text = (e.innerText || e.value || '').trim().replace(/\s+/g, ' ').slice(0, 80);
    const item = {i, tag: e.tagName.toLowerCase(), text};
    for (const [k, v] of [['type', e.type], ['name', e.name], ['label', (label(e) || '').trim().replace(/\s+/g, ' ').slice(0, 60)],
                           ['aria', e.getAttribute('aria-label')], ['placeholder', e.placeholder],
                           ['href', e.getAttribute('href')]]) if (v && v !== text) item[k] = String(v).slice(0, 80);
    if (e.tagName === 'SELECT') item.options = [...e.options].map(o => o.text.trim()).slice(0, 15);
    if (e.type === 'password') item.secret = true;
    out.push(item); if (out.length >= 90) break;
  }
  return out;
}"""

ACT_SYSTEM = """[[AQ-TASK:visual-act]] You are a careful manual tester driving a web page to carry out ONE test step.
You get the step, the steps done so far, the page's text, its numbered controls and its accessibility tree.
Reply with JSON only:
{"done": false, "why": "...", "action": {"do": "click|fill|select|check|press|goto", "element": <number>, "value": "...", "path": "/x"}}
or {"done": true, "why": "..."} when the step is complete, or {"done": true, "stuck": true, "why": "..."} when it cannot be done.
Use only the numbered controls you were given. For values, use only the test data tokens listed (copy them with the
braces, e.g. {mobile}) or plain sample text. Never type a password yourself."""

VERIFY_SYSTEM = """[[AQ-TASK:visual-verify]] You check ONE expected result of a test against what the page shows now.
Reply with JSON only: {"verdict": "pass|fail|unsure", "quote": "...", "why": "..."}
quote: words copied exactly from the page text that prove your verdict (what is shown). Answer "unsure" when the page
does not show enough to decide. Do not guess."""


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w@./-]+", " ", (t or "").lower())).strip()


class VisualQA:
    def __init__(self, project, *, role: str | None = None, ask_person: bool | None = None, page_text=None,
                 max_actions: int | None = None, url_of=None, find_click=None):
        cfg = (project.cfg.get("visual_qa") or {}) if project is not None else {}
        self.project, self.role = project, role
        self.ask_person = cfg.get("ask_person", True) if ask_person is None else ask_person
        self.ask_timeout = float(cfg.get("ask_timeout_s", 180))
        self.max_actions = int(max_actions or cfg.get("max_actions", 8))
        self.page_text = page_text
        self.url_of = url_of or (lambda path: project.url(path))
        self.find_click = find_click
        self.llm = None
        if project is not None and cfg.get("enabled", True):
            try:
                from agentqa.ai.client import model_for
                llm = model_for(project, "visual_qa")
                self.llm = llm if llm is not None and llm.available() else None
            except Exception as exc:  # noqa: BLE001
                warn(f"[visual-qa] no model: {exc}")
        self.trace: list[dict] = []

    # -- seeing ------------------------------------------------------------------------------
    def observe(self, page) -> dict:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:  # noqa: BLE001
            pass
        text = (self.page_text(page) if self.page_text else page.locator("body").inner_text(timeout=5000))
        try:
            els = page.evaluate(ELEMENTS_JS, MARK)
        except Exception:  # noqa: BLE001
            els = []
        aria = ""
        try:
            aria = page.locator("body").aria_snapshot(timeout=4000)[:3500]
        except Exception:  # noqa: BLE001
            pass
        from urllib.parse import urlparse
        return {"url": page.url, "path": urlparse(page.url).path or "/", "title": page.title(), "text": text[:6000],
                "elements": els, "aria": aria}

    def _image(self, page) -> bytes | None:
        """A screenshot only when the project consented to sending images and the model can see them."""
        if self.llm is None or not getattr(self.llm, "image_allowed", False):
            return None
        try:
            return page.screenshot(type="jpeg", quality=60, timeout=5000)
        except Exception:  # noqa: BLE001
            return None

    # -- acting ------------------------------------------------------------------------------
    def act(self, page, intent: str, *, tokens: dict | None = None, resolve=None, production: bool = False) -> dict:
        """Carry out one step. Returns {"ok", "by", "actions", "why"}."""
        done: list[str] = []
        if self.llm is not None:
            seen: set[str] = set()
            for _ in range(self.max_actions):
                ob = self.observe(page)
                payload = {"step": intent, "done_so_far": done, "page": {k: ob[k] for k in ("path", "title")},
                           "test_data_tokens": tokens or {}, "controls": ob["elements"], "text": ob["text"][:3500],
                           "accessibility_tree": ob["aria"]}
                out = self.llm.chat_json(ACT_SYSTEM, "PAYLOAD:\n" + json.dumps(payload), max_tokens=500,
                                         image_jpeg=self._image(page)) or {}
                if not out:
                    break
                if out.get("done"):
                    if out.get("stuck"):
                        return self._person_act(page, intent, done, f"the model is stuck: {out.get('why') or ''}".strip())
                    return {"ok": True, "by": "model", "actions": done, "why": str(out.get("why") or "")[:200]}
                act = out.get("action") or {}
                sig = json.dumps(act, sort_keys=True)
                if sig in seen:
                    return self._person_act(page, intent, done, "the model repeated an action without progress")
                seen.add(sig)
                ok, what = self._do(page, act, ob, resolve, production)
                if not ok:
                    return self._person_act(page, intent, done, what)
                done.append(what)
                self.trace.append({"t": round(time.time(), 3), "kind": "visual-qa", "text": what, "why": out.get("why")})
            else:
                return self._person_act(page, intent, done, f"not done after {self.max_actions} actions")
        return self._person_act(page, intent, done, "no AI model is configured" if self.llm is None else
                                "the AI model gave no usable answer")

    def _do(self, page, act: dict, ob: dict, resolve, production: bool) -> tuple[bool, str]:
        do = act.get("do")
        if do == "goto":
            path = str(act.get("path") or "")
            if not path.startswith(("/", "@")) or (self.project and not self.project.in_scope(path)):
                return False, f"the model asked to open '{path}', which is outside the test scope"
            page.goto(self.url_of(path), wait_until="domcontentloaded")
            return True, f"Opened {path}"
        if do == "press":
            key = str(act.get("value") or "Enter")
            if key not in ("Enter", "Tab", "Escape", "ArrowDown", "ArrowUp", "Space"):
                return False, f"key '{key}' is not allowed"
            page.keyboard.press(key)
            return True, f"Pressed {key}"
        el = next((e for e in ob["elements"] if e["i"] == act.get("element")), None)
        if el is None:
            return False, f"the model chose control {act.get('element')!r}, which is not on the page"
        name = el.get("text") or el.get("label") or el.get("aria") or el.get("placeholder") or el.get("name") or el["tag"]
        loc = page.locator(f'[{MARK}="{el["i"]}"]').first
        changes = do in ("fill", "select", "check") or (do == "click" and el["tag"] != "a")
        if production and changes:
            return False, f"'{do} {name}' could change data and this application is production (read-only)"
        if do == "click":
            loc.click(timeout=8000)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            return True, f"Clicked '{name}'"
        value = str(act.get("value") or "")
        if el.get("secret") and not re.fullmatch(r"\{[a-z_:]+\}", value):
            return False, "the model tried to type into a password box without a test data token"
        shown = value
        if resolve is not None and "{" in value:
            value = str(resolve(value))
        if do == "fill":
            loc.fill(value, timeout=8000)
            return True, f"Typed {shown!r} in '{name}'"
        if do == "select":
            loc.select_option(label=value, timeout=8000)
            return True, f"Chose {value!r} in '{name}'"
        if do == "check":
            loc.check(timeout=8000)
            return True, f"Ticked '{name}'"
        return False, f"unknown action {do!r}"

    def _person_act(self, page, intent: str, done: list[str], why: str) -> dict:
        if not self.ask_person:
            return {"ok": False, "by": None, "actions": done, "why": why, "asked": False}
        from agentqa import assist
        for _ in range(self.max_actions):
            ans = assist.ask(self.project, "navigate", f"Please guide this test step: {intent}", role=self.role,
                             agent="visual-qa", page=page, timeout=self.ask_timeout,
                             hint=f"{why}. Click what a tester would click next on the screenshot, or type 'done' "
                                  "when the step is complete.")
            if not ans:
                return {"ok": False, "by": None, "actions": done, "why": f"{why}; nobody guided the step", "asked": True}
            if str(ans.get("text") or "").strip().lower() == "done":
                return {"ok": True, "by": "person", "actions": done, "why": "a person confirmed the step was done"}
            if "x" in ans and "y" in ans:
                page.mouse.click(float(ans["x"]), float(ans["y"]))
                done.append(f"Clicked where the person showed ({ans['x']}, {ans['y']})")
            elif ans.get("text"):
                loc = self.find_click(page, str(ans["text"])) if self.find_click else page.get_by_text(str(ans["text"])).first
                if loc is None:
                    continue
                loc.click()
                done.append(f"Clicked '{ans['text']}' (shown by a person)")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:  # noqa: BLE001
                pass
        return {"ok": False, "by": "person", "actions": done, "why": "the step was not finished", "asked": True}

    # -- judging -----------------------------------------------------------------------------
    def verify(self, page, expectation: str) -> dict:
        """Returns {"verdict": pass|fail|unsure, "quote", "why", "by"}. A pass always carries a quote found on the page."""
        ob = self.observe(page)
        res = {"verdict": "unsure", "quote": "", "why": "no AI model is configured", "by": None}
        if self.llm is not None:
            payload = {"expected": expectation, "page": {k: ob[k] for k in ("path", "title")}, "text": ob["text"],
                       "accessibility_tree": ob["aria"]}
            out = self.llm.chat_json(VERIFY_SYSTEM, "PAYLOAD:\n" + json.dumps(payload), max_tokens=400,
                                     image_jpeg=self._image(page)) or {}
            verdict = str(out.get("verdict") or "").lower()
            quote = str(out.get("quote") or "").strip()
            res = {"verdict": verdict if verdict in ("pass", "fail") else "unsure", "quote": quote[:300],
                   "why": str(out.get("why") or "")[:300], "by": "model"}
            if not out:
                res["why"] = "the AI model gave no usable answer"
            elif res["verdict"] != "unsure" and not self.quote_on_page(quote, ob["text"] + "\n" + ob["aria"]):
                res.update(verdict="unsure", why=f"the model's quote {quote[:80]!r} is not on the page, so its "
                                                 f"'{verdict}' is not accepted")
        if res["verdict"] == "unsure" and self.ask_person:
            from agentqa import assist
            ans = assist.ask(self.project, "confirm", f"Check the expected result: {expectation}", role=self.role,
                             agent="visual-qa", page=page, timeout=self.ask_timeout,
                             options=["Yes, the page shows it", "No, it does not"], hint=res["why"])
            if ans:
                ok = not (ans.get("option") == 1 or ans.get("ok") is False)
                res = {"verdict": "pass" if ok else "fail", "quote": "", "by": "person",
                       "why": "confirmed by a person on the live screen" if ok else "a person said the page does not show it"}
        self.trace.append({"t": round(time.time(), 3), "kind": "visual-qa", "text": f"verify: {res['verdict']} ({res['why']})",
                           "quote": res["quote"]})
        return res

    @staticmethod
    def quote_on_page(quote: str, text: str) -> bool:
        from agentqa.ai.router import redact
        q = _norm(quote)
        if len(q) < 4:
            return False
        return q in _norm(text) or q in _norm(redact(text))
