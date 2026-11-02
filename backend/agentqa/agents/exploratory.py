"""Exploratory Tester agent: unscripted checks that the designed tests do not cover.

For each role it behaves like a curious user, using a seeded random walk so a
run can be repeated exactly:

1. Wanders the menus, preferring screens it has not seen yet.
2. Fills the data-entry forms it meets with odd but harmless input: text
   fields get a marker such as ``x<b>aq12345</b>`` (bold tags, never script),
   and other fields get valid values. Browser validation is switched off so
   the server decides.
3. Types the addresses of screens that other roles found straight into the
   address bar, to look for permission leaks.

On every step it checks for server errors, JavaScript errors, failed page
resources (scripts, styles, images), input echoed back as live HTML, and
permission leaks measured against the approved access rules. Once per run it
also makes passive security checks: response headers, cookie flags and
server-version disclosure.

It never follows logout or delete links, and never submits a form that has a
password field or a required file field or whose button matches ``exploratory.never_submit``
(approve, reject, pay and so on): state-changing business actions are left to
the YAML workflows. Findings use the same signatures as test failures, so
Triage merges a finding with a failing test about the same screen.
"""
from __future__ import annotations

import random
import re
import time
from urllib.parse import urldefrag, urlparse

from playwright.sync_api import sync_playwright

from agentqa import language, live
from agentqa.agents.designer import USABLE
from agentqa.agents.explorer import PAGE_SCRIPT
from agentqa.config import Project
from agentqa.store import Store, now
from agentqa.util import guess_semantic, log, path_pattern, valid_value, warn

AGENT = "exploratory"
SEV_ORDER = ["Critical", "High", "Medium", "Low"]
TEXTLIKE = {"text", "search", "textarea", ""}
NO_MARKER_SEMANTICS = {"email", "mobile", "pincode", "date", "number", "aadhaar", "pan"}

BROKEN_IMAGES = """() => [...document.images].filter(i => i.complete && i.naturalWidth === 0 && i.src)
  .map(i => i.src).slice(0, 10)"""
REFLECTED = """tokens => tokens.filter(t => [...document.querySelectorAll('b')].some(b => (b.textContent || '').trim() === t))"""


_PROJ: list = []


def _rel(url: str) -> str:
    if _PROJ and _PROJ[0].is_internal(url):
        return _PROJ[0].rel(url)          # '@department/clerk/queue' on a second portal
    u = urlparse(url)
    return (u.path or "/") + (f"?{u.query}" if u.query else "")


class Explorer:
    """State for one Exploratory Tester run."""

    def __init__(self, project: Project, store: Store):
        self.project, self.store = project, store
        self.cfg = project.cfg.get("exploratory", {})
        self.ex = project.cfg["explore"]
        self.oracles = project.cfg["oracles"]
        self.login_path = project.cfg["login"]["url"]
        _PROJ[:] = [project]
        self.exclude = [re.compile(p, re.I) for p in self.ex["exclude_patterns"]]
        self.never = [re.compile(p, re.I) for p in self.cfg.get("never_submit", [])]
        self.rng = random.Random(int(self.cfg.get("seed", 7)))
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.run_id = f"X-{stamp}"
        self.evidence_dir = project.runs_dir / f"exploratory-{stamp}"
        self.findings: dict[str, dict] = {}
        self.steps = 0
        self.security_done = False
        self.errors: list[str] = []
        self.bad_resources: list[tuple] = []

    # ---- findings -----------------------------------------------------------------
    def add(self, page, sig: str, severity: str, title: str, detail: str, role: str, path: str,
            steps: list[str], expected: str, rule: dict | None = None) -> None:
        f = self.findings.get(sig)
        if f:
            f["roles"].add(role)
            if detail not in f["details"]:
                f["details"].append(detail)
            return
        evidence = []
        if page is not None:
            try:
                self.evidence_dir.mkdir(parents=True, exist_ok=True)
                shot = self.evidence_dir / f"finding-{len(self.findings) + 1:03d}.png"
                page.screenshot(path=str(shot), full_page=True, timeout=8000)
                evidence.append({"kind": "screenshot", "role": role, "path": str(shot), "url": page.url})
            except Exception:  # noqa: BLE001
                pass
        self.findings[sig] = {"sig": sig, "severity": severity, "title": title, "details": [detail],
                              "roles": {role}, "path": path, "url": self.project.url(path), "steps": steps,
                              "expected": expected, "evidence": evidence,
                              "rule_id": (rule or {}).get("rule"), "req_id": (rule or {}).get("req")}
        level = "bad" if severity in ("Critical", "High") else "warn"
        if page is not None:
            live.shot(page, AGENT, "finding", f"{severity}: {title}", role=role, path=path, severity=severity,
                      detail=detail[:300], sig=sig, level=level)
        else:
            live.emit(AGENT, "finding", f"{severity}: {title}", role=role, path=path, severity=severity,
                      detail=detail[:300], sig=sig, level=level)

    @staticmethod
    def _how(role: str) -> str:
        return "Stay logged out." if role == "anonymous" else f"Log in as {role}."

    # ---- page checks --------------------------------------------------------------------
    def check_page(self, page, role: str, path: str, status: int, info: dict, came_from: str | None) -> None:
        low = (info.get("body_text") or "").lower()
        how = self._how(role)
        if status >= 500 or any(p in low for p in self.oracles["server_error_patterns"]):
            self.add(page, f"page:{path.split('?')[0]}", "High", f"{path.split('?')[0]} fails to load: HTTP {status}",
                     f"{path} answered HTTP {status}" + (" with server error text" if status < 500 else ""), role, path,
                     [how, f"Open {self.project.url(path)}."], "The page loads without a server error.")
        elif status in (404, 410) and came_from:
            self.add(page, f"link:{path}", "Medium", f"Broken link to {path} (HTTP {status}) on {came_from}",
                     f"{path} -> HTTP {status} (linked from {came_from})", role, path,
                     [how, f"Open {self.project.url(came_from)}.", f"Click the link to {path}."],
                     "Every link opens a working page.")
        errs = [e for e in self.errors if "favicon" not in e and not e.startswith("Failed to load resource")]
        if errs:
            self.add(page, f"js:{path.split('?')[0]}", "Low", f"JavaScript error on {path.split('?')[0]}",
                     "; ".join(dict.fromkeys(errs))[:400], role, path,
                     [how, f"Open {self.project.url(path)}.", "Open the browser console (F12)."],
                     "The page runs without JavaScript errors.")
        try:
            broken = page.evaluate(BROKEN_IMAGES)
        except Exception:  # noqa: BLE001
            broken = []
        resources = {(_rel(u), f"HTTP {s}", t) for s, u, t in self.bad_resources}
        resources |= {(_rel(u), "image did not load", "image") for u in broken}
        for res, why, kind in sorted(resources):
            if res.endswith("favicon.ico"):
                continue
            self.add(page, f"resource:{res}", "Low", f"Missing {kind} {res} on {path.split('?')[0]}",
                     f"{res}: {why} (used by {path})", role, path, [how, f"Open {self.project.url(path)}."],
                     "Every script, style sheet and image on the page loads.")

    def check_security(self, page, resp, role: str, path: str) -> None:
        if self.security_done or not resp or not self.cfg.get("security_checks", True):
            return
        self.security_done = True
        try:
            h = {k.lower(): v for k, v in resp.all_headers().items()}
        except Exception:  # noqa: BLE001
            return
        https = self.project.base_url.startswith("https")
        csp = h.get("content-security-policy", "")
        missing, serious = [], False
        if not csp:
            missing.append("Content-Security-Policy")
        if "x-frame-options" not in h and "frame-ancestors" not in csp:
            missing.append("X-Frame-Options (or CSP frame-ancestors): pages can be framed (clickjacking)")
            serious = True
        if h.get("x-content-type-options", "").lower() != "nosniff":
            missing.append("X-Content-Type-Options: nosniff")
            serious = True
        if "referrer-policy" not in h:
            missing.append("Referrer-Policy")
        if https and "strict-transport-security" not in h:
            missing.append("Strict-Transport-Security")
            serious = True
        live.shot(page, AGENT, "observe", f"Checked the response headers of {path}: "
                  + (f"{len(missing)} security header(s) missing" if missing else "all present"), role=role, path=path,
                  level="warn" if missing else "ok")
        if missing:
            self.add(None, "security:headers", "Medium" if serious else "Low",
                     "Security headers are missing", "Missing: " + "; ".join(missing), role, path,
                     ["Open any page with the browser's developer tools (F12), Network tab.",
                      f"Select the request for {self.project.url(path)} and read its response headers."],
                     "Responses send Content-Security-Policy, X-Frame-Options or frame-ancestors, "
                     "X-Content-Type-Options: nosniff and Referrer-Policy"
                     + (", and Strict-Transport-Security over HTTPS." if https else "."))
        shown = [f"{k}: {h[k]}" for k in ("server", "x-powered-by", "x-aspnet-version", "x-aspnetmvc-version")
                 if k in h and re.search(r"\d", h[k])]
        if shown:
            self.add(None, "security:disclosure", "Low", "The server reveals its software version",
                     "; ".join(shown), role, path,
                     [f"Open {self.project.url(path)} with developer tools and read the response headers."],
                     "Responses do not reveal server software versions.")

    def check_cookies(self, ctx, page, role: str) -> None:
        if not self.cfg.get("security_checks", True):
            return
        https = self.project.base_url.startswith("https")
        host = urlparse(self.project.base_url).hostname or ""
        for c in ctx.cookies():
            if host and host not in (c.get("domain") or ""):
                continue
            problems = []
            if not c.get("httpOnly"):
                problems.append("not HttpOnly (scripts can read it)")
            if https and not c.get("secure"):
                problems.append("not Secure (sent over plain HTTP)")
            if (c.get("sameSite") or "None") == "None":
                problems.append("SameSite=None or missing")
            live.emit(AGENT, "observe", f"Cookie '{c['name']}' after login as {role}: "
                      + ("; ".join(problems) if problems else "HttpOnly, SameSite " + str(c.get("sameSite"))),
                      role=role, level="warn" if problems else "ok")
            if problems:
                self.add(page, f"security:cookie:{c['name']}", "Medium" if not c.get("httpOnly") else "Low",
                         f"Cookie '{c['name']}' lacks protective flags", f"{c['name']}: " + "; ".join(problems),
                         role, _rel(page.url),
                         [self._how(role), "Open developer tools (F12), Application tab, Cookies.",
                          f"Inspect the '{c['name']}' cookie."],
                         "Session cookies are HttpOnly, SameSite=Lax or Strict, and Secure over HTTPS.")

    # ---- navigation -------------------------------------------------------------------
    def visit(self, page, role: str, url: str, came_from: str | None, how: str, probe: bool = False) -> dict | None:
        path = _rel(url)
        self.errors.clear()
        self.bad_resources.clear()
        started = time.time()
        try:
            resp = page.goto(url, wait_until="load")
        except Exception as exc:  # noqa: BLE001
            live.emit(AGENT, "issue", f"Could not open {path}: {exc.__class__.__name__}", role=role, path=path,
                      level="warn")
            return None
        page.wait_for_timeout(150)
        status = resp.status if resp else 0
        if status < 400:
            language.ensure_english(page, self.project, agent=AGENT, role=role, ask=False)
        try:
            info = page.evaluate(PAGE_SCRIPT)
        except Exception:  # noqa: BLE001
            return None
        self.steps += 1
        final = _rel(page.url)
        live.shot(page, AGENT, "navigate", f"{how} {path}" + (f" -> {final}" if final != path else "")
                  + f" (HTTP {status})", role=role, path=path, parent=came_from, status=status,
                  page_title=info["title"], load_ms=int((time.time() - started) * 1000), probe=probe or None,
                  level="bad" if status >= 500 else ("warn" if status >= 400 and not probe else None))
        self.check_security(page, resp, role, path)
        self.check_page(page, role, path, status, info, came_from)
        return {"path": path, "final": final, "status": status, "info": info}

    def blocked(self, page, path: str, status: int, final: str, info: dict) -> str | None:
        text = (info.get("body_text") or "").lower()
        if status in (401, 403):
            return f"HTTP {status}"
        if status in (404, 410):
            return f"HTTP {status} (hidden)"
        if self.project.is_login_path(final) and not self.project.is_login_path(path):
            return "sent to login"
        if any(p in text for p in self.oracles["denied_patterns"]):
            return "an access-denied message"
        return None

    # ---- forms ------------------------------------------------------------------------
    def safe_form(self, form: dict, path: str = "/") -> str | None:
        if self.project.is_production(path):
            return "is on an application marked Production (read-only there)"
        types = {(f.get("type") or "").lower() for f in form["fields"]}
        if "password" in types:
            return "has a password field"
        if any((f.get("type") or "").lower() == "file" and f.get("required") for f in form["fields"]):
            return "needs a file upload"
        what = f"{form.get('submit_text', '')} {form.get('action', '')}"
        if any(p.search(what) for p in self.never + self.exclude):
            return f"'{(form.get('submit_text') or form.get('action'))}' changes business state; left to workflows"
        if not any((f.get("type") or "").lower() not in ("hidden", "checkbox", "radio", "select", "submit", "button")
                   and f.get("tag") != "select" for f in form["fields"]):
            return "has no fields to type into"
        return None

    def try_form(self, page, role: str, path: str, index: int, form: dict) -> dict | None:
        floc = page.locator("form").nth(index)
        tokens: dict[str, tuple] = {}
        live.shot(page, AGENT, "observe", f"Trying the form on {path} with unusual input", floc, role=role, path=path)
        for f in form["fields"]:
            name, ftype, tag = f.get("name"), (f.get("type") or "").lower(), f.get("tag")
            if not name or ftype in ("hidden", "submit", "button", "reset", "image"):
                continue
            loc = floc.locator(f'[name="{name}"]').first
            label = f.get("label") or f.get("placeholder") or name
            try:
                if not loc.is_visible():
                    continue
                if tag == "select":
                    opts = [o["value"] for o in f.get("options") or [] if (o.get("value") or "").strip()]
                    if not opts:
                        continue
                    choice = self.rng.choice(opts)
                    loc.select_option(choice)
                    shown = f"Chose '{choice}' in {label}"
                elif ftype in ("checkbox", "radio"):
                    loc.check()
                    shown = f"Ticked {label}"
                elif ftype in TEXTLIKE and guess_semantic(f) not in NO_MARKER_SEMANTICS:
                    token = f"aq{self.rng.randint(10000, 99999)}"
                    value = f"x<b>{token}</b>"
                    loc.fill(value)
                    tokens[token] = (name, label)
                    shown = f"Typed {value} into {label} (marker: would turn bold if echoed as HTML)"
                else:
                    value = valid_value(f) or "1"
                    loc.fill(value)
                    shown = f"Typed '{value}' into {label}"
            except Exception:  # noqa: BLE001
                continue
            live.shot(page, AGENT, "action", shown, loc, role=role, path=path, field=label)
        floc.evaluate("f => { f.noValidate = true; }")
        btn = floc.locator("button[type=submit], input[type=submit], button:not([type])")
        self.errors.clear()
        self.bad_resources.clear()
        status = 0
        try:
            with page.expect_navigation(wait_until="load", timeout=int(self.ex.get("timeout_ms", 15000))) as nav:
                if btn.count():
                    live.shot(page, AGENT, "action", f"Clicked '{(btn.first.inner_text() or 'Submit').strip()}' "
                              "(browser validation off, so the server decides)", btn.first, role=role, path=path)
                    btn.first.click()
                else:
                    floc.evaluate("f => f.requestSubmit ? f.requestSubmit() : f.submit()")
            resp = nav.value
            status = resp.status if resp else 0
        except Exception as exc:  # noqa: BLE001
            live.emit(AGENT, "observe", f"The form on {path} did not navigate ({exc.__class__.__name__})", role=role,
                      path=path)
        page.wait_for_timeout(200)
        self.steps += 1
        final = _rel(page.url)
        try:
            info = page.evaluate(PAGE_SCRIPT)
            echoed = page.evaluate(REFLECTED, list(tokens)) if tokens else []
        except Exception:  # noqa: BLE001
            return None
        how = self._how(role)
        live.shot(page, AGENT, "observe", f"Server answered HTTP {status} on {final}"
                  + (f"; {len(echoed)} marker(s) came back as live HTML" if echoed else ""),
                  role=role, path=final, status=status, level="bad" if echoed or status >= 500 else None)
        for token in echoed:
            name, label = tokens[token]
            # keyed on the page that reflects the input (as OWASP ZAP reports it), so both merge into one defect
            self.add(page, f"xss:{path_pattern(final.split('?')[0] or '/')}:{name}", "High",
                     f"Input in {label} is shown as HTML on {final.split('?')[0]} (possible cross-site scripting)",
                     f"Typed x<b>{token}</b> into {label} on {path}; the result page {final} rendered it in bold, "
                     f"so the input was inserted as HTML instead of text.", role, path,
                     [how, f"Open {self.project.url(path)}.", f"Type x<b>test</b> into {label} and submit.",
                      "The word 'test' appears in bold: the page inserts what users type as HTML."],
                     "Whatever users type is shown as plain text (HTML-escaped).")
        if status >= 500 or any(p in (info.get("body_text") or "").lower() for p in self.oracles["server_error_patterns"]):
            self.add(page, f"form-crash:{path.split('?')[0]}", "High",
                     f"The form on {path.split('?')[0]} crashes on unusual input (HTTP {status})",
                     f"Submitting unusual input on {path} returned HTTP {status}.", role, path,
                     [how, f"Open {self.project.url(path)}.", "Type text containing < and > characters and submit."],
                     "The server rejects bad input with a validation message, not a crash.")
        self.check_page(page, role, final, status if status < 500 else 200, info, None)
        return {"path": final, "final": final, "status": status, "info": info}

    # ---- one role ---------------------------------------------------------------------------
    def walk(self, browser, role: str, others: dict[str, set], reached: set, denied: dict) -> int:
        from agentqa import login_flow
        state = None
        if role != "anonymous":
            try:
                state = login_flow.ensure_session(browser, self.project, role, AGENT)
            except Exception as exc:  # noqa: BLE001
                warn(f"exploratory: login failed for {role}: {exc}")
                live.emit(AGENT, "issue", f"Login failed for {role}: {exc}", role=role, level="bad")
                return 0
        ctx = browser.new_context(storage_state=str(state) if state else None)
        ctx.set_default_timeout(int(self.ex.get("timeout_ms", 15000)))
        page = ctx.new_page()
        page.on("console", lambda m: self.errors.append(m.text[:300]) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(f"Uncaught {str(e)[:300]}"))
        page.on("response", lambda r: self.bad_resources.append((r.status, r.url, r.request.resource_type))
                if r.status >= 400 and r.request.resource_type in ("script", "stylesheet", "image", "font") else None)
        start_steps = self.steps
        live.emit(AGENT, "persona", f"{role}: a curious user who wanders the menus, tries the forms with odd input, "
                  f"then types other roles' addresses directly", role=role)
        try:
            if role != "anonymous":
                page.goto(self.project.url("/", self.project.app_of(role)), wait_until="domcontentloaded")
                self.check_cookies(ctx, page, role)
        except Exception as exc:  # noqa: BLE001
            warn(f"exploratory: login failed for {role}: {exc}")
            live.emit(AGENT, "issue", f"Login failed for {role}: {exc}", role=role, level="bad")
            ctx.close()
            return 0

        budget = int(self.cfg.get("max_steps_per_role", 20))
        seen_patterns: dict[str, int] = {}
        tried_forms: set[str] = set()
        start = self.project.url(self.ex["start_paths"][0]) if role == "anonymous" else page.url
        cur = self.visit(page, role, start, None, "Opened")
        used = 1
        while cur and used < budget:
            info, path = cur["info"], cur["final"]
            seen_patterns[path_pattern(path)] = seen_patterns.get(path_pattern(path), 0) + 1
            forms = []
            if self.cfg.get("submit_forms", True):
                for i, form in enumerate(info["forms"]):
                    key = f"{path_pattern(path)}#{i}"
                    if key in tried_forms:
                        continue
                    why = self.safe_form(form, path)
                    if why:
                        tried_forms.add(key)
                        live.emit(AGENT, "skip", f"Left the form on {path} alone: it {why}", role=role, path=path)
                        continue
                    forms.append((i, form, key))
            if forms and self.rng.random() < 0.6:
                i, form, key = self.rng.choice(forms)
                tried_forms.add(key)
                cur = self.try_form(page, role, path, i, form) or cur
                used += 1
                continue
            links = []
            for link in info["links"]:
                href = urldefrag(link["href"])[0]
                if not href.startswith("http") or not self.project.is_internal(href):
                    continue
                rel = _rel(href)
                if any(p.search(rel) for p in self.exclude) or language.is_switch(link["text"], href):
                    continue
                if role != "anonymous" and (self.project.is_login_path(rel)
                                            or self.project.split_path(rel)[0] != self.project.app_of(role)):
                    continue
                links.append((rel, href, link["text"]))
            # screens behind buttons and JavaScript menus (the Explorer clicked its way to them) count as menu entries
            known = {r for r, _, _ in links}
            for rp in sorted(reached):
                if rp not in known and "{" not in rp and not self.project.is_login_path(rp) \
                        and not any(x.search(rp) for x in self.exclude):
                    links.append((rp, self.project.url(rp), f"menu item for {rp}"))
            if not links:
                cur = self.visit(page, role, self.project.url(self.ex["start_paths"][0]), None, "Went back to")
                used += 1
                continue
            weights = [6.0 if path_pattern(r) not in seen_patterns else 1.0 / (1 + seen_patterns[path_pattern(r)])
                       for r, _, _ in links]
            rel, href, text = self.rng.choices(links, weights=weights)[0]
            nxt = self.visit(page, role, href, path, f"Clicked '{text[:40] or rel}' ->")
            used += 1
            cur = nxt or cur

        # direct probes: screens other roles reached that this role did not
        probes = []
        for other, paths in others.items():
            for p in sorted(paths - reached):
                if self.project.is_login_path(p) or any(x.search(p) for x in self.exclude):
                    continue
                if path_pattern(p) not in {path_pattern(x) for x, _ in probes}:
                    probes.append((p, other))
        limit = int(self.cfg.get("probe_limit", 15))
        if probes:
            live.emit(AGENT, "persona", f"{role}: trying {min(len(probes), limit)} screen(s) that other roles can open, "
                      f"by typing their addresses", role=role)
        for p, other in probes[:limit]:
            res = self.visit(page, role, self.project.url(p), None, f"Typed the address of a {other} screen:", probe=True)
            if not res:
                continue
            how_blocked = self.blocked(page, p, res["status"], res["final"], res["info"])
            if how_blocked:
                live.emit(AGENT, "verdict", f"Blocked as expected ({how_blocked})", role=role, path=p, level="ok")
                continue
            if res["status"] >= 500:
                continue  # reported by check_page
            rule = denied.get((role, p))
            if role == "anonymous" and not rule:
                rule = {"screen": p, "baseline": True}
            if rule:
                who = "An anonymous visitor" if role == "anonymous" else f"Role '{role}'"
                self.add(page, f"access:{p}", "Critical",
                         f"{rule.get('screen') or p} ({p}) is open to roles that must be blocked",
                         f"{who} opened {p} by typing its address (HTTP {res['status']}, ended on {res['final']}).",
                         role, p, [self._how(role), f"Type {self.project.url(p)} into the address bar."],
                         ("Only the permitted roles can open this screen." if not rule.get("baseline")
                          else "Screens for logged-in users require logging in."),
                         rule if not rule.get("baseline") else None)
            else:
                live.emit(AGENT, "verdict", f"Opened {p}; no approved rule says whether {role} may (see the "
                          f"Questions page)", role=role, path=p, level="warn")
        ctx.close()
        return self.steps - start_steps


def _denied_rules(store: Store) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    for r in store.all("SELECT * FROM rules WHERE kind IN ('access_only', 'access_deny')"):
        if r["status"] not in USABLE:
            continue
        for m in r.get("matched") or []:
            for role in m.get("deny") or []:
                out.setdefault((role, m["path"]), {"rule": r["id"], "req": r["req_id"], "screen": m.get("title")})
    return out


def explore(project: Project, store: Store, roles: list[str] | None = None) -> dict:
    x = Explorer(project, store)
    roles = roles or list(project.roles())
    if project.cfg["explore"].get("include_anonymous", True) and "anonymous" not in roles:
        roles = ["anonymous"] + roles
    reached: dict[str, set] = {}
    for s in store.all("SELECT role, path, status, final_url FROM screens"):
        if (s["status"] or 0) < 400 and _rel(s["final_url"] or s["path"]).split("?")[0] == s["path"].split("?")[0]:
            reached.setdefault(s["role"], set()).add(s["path"])
    if not reached:
        warn("No app map yet: run the Explorer first so the Exploratory Tester knows other roles' screens.")
    denied = _denied_rules(store)
    live.emit(AGENT, "start", f"Exploring as {len(roles)} role(s), up to {x.cfg.get('max_steps_per_role', 20)} "
              f"steps each (seed {x.cfg.get('seed', 7)}); {len(denied)} access rule(s) to check against",
              roles=roles)
    import os
    from agentqa import testdata
    testdata.run_steps(project, "setup", "exploratory", agent=AGENT)
    headed = os.environ.get("AGENTQA_HEADED") == "1"
    per_role = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed and project.cfg["execution"].get("headless", True),
                                     slow_mo=int(os.environ.get("AGENTQA_SLOWMO", "0")) if headed else 0)
        for role in roles:
            others = {r: p for r, p in reached.items() if r != role}
            per_role[role] = x.walk(browser, role, others, reached.get(role, set()), denied)
            log(f"  {role}: {per_role[role]} step(s)")
        browser.close()
    testdata.run_steps(project, "cleanup", "exploratory", agent=AGENT)

    store.exec("DELETE FROM findings WHERE run_id NOT LIKE 'Z-%'")
    for f in sorted(x.findings.values(), key=lambda f: (SEV_ORDER.index(f["severity"]), f["sig"])):
        store.insert("findings", {"run_id": x.run_id, "sig": f["sig"], "severity": f["severity"], "title": f["title"],
                                  "roles": sorted(f["roles"]), "path": f["path"], "url": f["url"],
                                  "steps": "\n".join(f["steps"]), "expected": f["expected"],
                                  "detail": "\n".join(f["details"]), "evidence": f["evidence"],
                                  "rule_id": f["rule_id"], "req_id": f["req_id"], "created_at": now()})
    by_sev: dict[str, int] = {}
    for f in x.findings.values():
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
    summary = {"run_id": x.run_id, "steps": x.steps, "findings": len(x.findings), "by_severity": by_sev,
               "per_role": per_role}
    store.set_meta("exploratory_run", x.run_id)
    store.set_meta("exploratory", summary)
    live.emit(AGENT, "summary", f"{x.steps} step(s) as {len(roles)} role(s); {len(x.findings)} finding(s)"
              + (" (" + ", ".join(f"{n} {s.lower()}" for s, n in sorted(by_sev.items(),
                                                                       key=lambda kv: SEV_ORDER.index(kv[0]))) + ")"
                 if by_sev else ""), **{k: v for k, v in summary.items() if k != "per_role"})
    return summary
