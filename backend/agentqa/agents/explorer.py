"""Explorer agent: logs in as each role and maps the application.

Follows same-origin links breadth-first (never submits forms, never follows
logout/delete links) and records every screen: status, load time, headings,
links, forms with field attributes, buttons, console errors and basic
accessibility gaps. Deterministic; no model needed.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from pathlib import Path
from urllib.parse import urldefrag, urlparse

from playwright.sync_api import Page, sync_playwright

from agentqa import assist, language, live
from agentqa.config import Project
from agentqa.store import Store, now
from agentqa.util import log, path_pattern, warn

WIDGET_JS = (Path(__file__).resolve().parent.parent / "runtime" / "widgets.js").read_text(encoding="utf-8")
PAGE_SCRIPT = r"""
() => {
  const aqW = __AQW__;
  const txt = el => (el ? (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ') : '');
  const labelRaw = el => {
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return txt(l); }
    const wrap = el.closest('label'); if (wrap) return txt(wrap);
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const by = el.getAttribute('aria-labelledby');
    if (by) return by.split(' ').map(i => txt(document.getElementById(i))).join(' ');
    return '';
  };
  const labelFor = el => labelRaw(el).replace(/\s*[(\[](optional|required|mandatory)[)\]]\s*$/i, '').replace(/\s*\*\s*$/, '').trim();
  const forms = [...document.querySelectorAll('form')].map((f, fi) => ({
    index: fi, id: f.id || '', action: f.getAttribute('action') || '', method: (f.getAttribute('method') || 'get').toLowerCase(),
    submit_text: txt(f.querySelector('button[type=submit], input[type=submit], button:not([type])')),
    fields: [...f.querySelectorAll('input, select, textarea')].filter(e => !['submit','button','reset','image'].includes((e.type||'').toLowerCase())).map(e => {
      const base = (e.getAttribute('type') || (e.tagName === 'SELECT' ? 'select' : e.tagName === 'TEXTAREA' ? 'textarea' : 'text')).toLowerCase();
      const hidden = base === 'hidden' || !(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
      const w = hidden && e.name ? aqW(e) : null;
      const wtype = w ? ({datepicker: 'date', richtext: 'textarea', listbox: 'select', combobox: 'select', text: 'text'})[w.kind] : null;
      return {
        tag: w ? (w.kind === 'richtext' ? 'textarea' : (wtype === 'select' ? 'select' : 'input')) : e.tagName.toLowerCase(),
        type: wtype || base, widget: w ? w.kind : null, ui: w ? w.ui : null,
        name: e.name || '', id: e.id || '', label: w ? w.label : labelFor(e), placeholder: w ? w.placeholder : (e.getAttribute('placeholder') || ''),
        required: w ? w.required : e.required, maxlength: w ? w.maxlength : e.getAttribute('maxlength'), minlength: e.getAttribute('minlength'),
        pattern: e.getAttribute('pattern'), min: e.getAttribute('min'), max: e.getAttribute('max'),
        accept: e.getAttribute('accept'), multiple: !!e.multiple || !!(w && w.multiple),
        options: e.tagName === 'SELECT' ? [...e.options].map(o => ({value: o.value, text: txt(o)})) : (w && w.options) || null,
      };
    }),
  }));
  const a11y = {
    img_no_alt: [...document.querySelectorAll('img')].filter(i => !i.hasAttribute('alt')).map(i => i.getAttribute('src') || '').slice(0, 20),
    inputs_no_label: [...document.querySelectorAll('input, select, textarea')]
      .filter(e => !['hidden','submit','button','reset','image'].includes((e.type||'').toLowerCase()))
      .filter(e => e.offsetWidth || e.offsetHeight || e.getClientRects().length)
      .filter(e => !labelFor(e) && !e.getAttribute('title')).map(e => e.name || e.id || e.tagName.toLowerCase()).slice(0, 20),
    buttons_no_name: [...document.querySelectorAll('button, [role=button]')].filter(b => !txt(b) && !b.getAttribute('aria-label') && !b.getAttribute('title')).length,
    html_lang: document.documentElement.getAttribute('lang') || '',
    has_h1: !!document.querySelector('h1'),
  };
  return {
    title: document.title || '',
    headings: [...document.querySelectorAll('h1, h2')].map(txt).filter(Boolean).slice(0, 12),
    links: [...document.querySelectorAll('a[href]')].map(a => ({href: a.href, text: txt(a).slice(0, 80)})).slice(0, 300),
    buttons: [...document.querySelectorAll('button, input[type=submit], [role=button]')].map(b => txt(b) || b.value || '').filter(Boolean).slice(0, 60),
    forms, a11y,
    body_text: txt(document.body).slice(0, 4000),
  };
}
"""
PAGE_SCRIPT = PAGE_SCRIPT.replace("__AQW__", WIDGET_JS)


def login(page: Page, project: Project, role: str, agent: str = "explorer") -> bool:
    """Log in as a role the way a tester does (see agentqa.login_flow). True when an OTP was entered."""
    from agentqa import login_flow
    return login_flow.login(page, project, role, agent)


def _shape(data) -> tuple[str, list[str]]:
    """'object' / 'list of N' plus the field names a caller can rely on."""
    if isinstance(data, dict):
        return "object", sorted(data)[:40]
    if isinstance(data, list):
        first = next((x for x in data if isinstance(x, dict)), None)
        return f"list of {len(data)}", sorted(first)[:40] if first else []
    return type(data).__name__, []


def _json(resp):
    try:
        if "json" in (resp.headers.get("content-type") or ""):
            return resp.json()
    except Exception:  # noqa: BLE001
        return None
    return None


AUTH_HEADERS = ("authorization", "x-auth-token", "x-access-token", "x-api-key", "x-token", "token", "x-session-token",
                "x-csrf-token", "x-xsrf-token", "x-authorization", "auth-token", "access-token", "x-id-token")
STORAGE_JS = "() => ({local: Object.fromEntries(Object.entries(localStorage)), session: Object.fromEntries(Object.entries(sessionStorage))})"


def _token_source(value: str, stores: dict, cookies: list) -> dict | None:
    """Where a header value lives in the browser: a storage key (plain, or inside a JSON object) or a cookie.
    Returns {"source", "key", "path", "prefix"} or None when it is only in the page's memory."""
    v = value.strip()
    for store_name in ("local", "session"):
        for key, raw in (stores.get(store_name) or {}).items():
            raw = str(raw)
            if not raw:
                continue
            if raw == v:
                return {"source": store_name, "key": key, "path": [], "prefix": ""}
            if len(raw) >= 16 and v.endswith(raw):
                return {"source": store_name, "key": key, "path": [], "prefix": v[: -len(raw)]}
            if raw[:1] in "{[":
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                found = _find_in(obj, v)
                if found is not None:
                    return {"source": store_name, "key": key, "path": found[0], "prefix": found[1]}
    for c in cookies:
        cv = str(c.get("value") or "")
        if len(cv) >= 16 and (cv == v or v.endswith(cv)):
            return {"source": "cookie", "key": c.get("name"), "path": [], "prefix": v[: -len(cv)] if v != cv else ""}
    return None


def _find_in(obj, value: str, path: list | None = None, depth: int = 0):
    path = path or []
    if depth > 4:
        return None
    if isinstance(obj, dict):
        items = obj.items()
    elif isinstance(obj, list):
        items = enumerate(obj)
    else:
        s = str(obj)
        if s and len(s) >= 16 and (s == value or value.endswith(s)):
            return path, value[: -len(s)] if value != s else ""
        return None
    for k, v in items:
        r = _find_in(v, value, path + [k], depth + 1)
        if r is not None:
            return r
    return None


def api_auth_profile(page: Page, project: Project, role: str, calls: list, current: dict | None) -> dict | None:
    """How this role's screens authenticate their API calls: the header they send and where its value is kept
    (a browser storage key, a cookie, or only in memory). No value is stored, only the place to read it from."""
    if current and current.get("source") in ("local", "session", "cookie"):
        return current
    try:
        stores = page.evaluate(STORAGE_JS)
        cookies = page.context.cookies()
    except Exception:  # noqa: BLE001
        return current
    best = current
    for r in list(calls):
        try:
            if not (200 <= r.status < 300) or not project.is_api_url(r.url):
                continue
            headers = r.request.all_headers()
        except Exception:  # noqa: BLE001
            continue
        for name in AUTH_HEADERS:
            value = headers.get(name)
            if not value or len(value) < 8:
                continue
            where = _token_source(value, stores, cookies)
            prof = {"header": name, "api": project.rel(r.url) if project.is_internal(r.url) else r.url, **(where or {"source": "memory"})}
            if where:
                return prof
            best = best or prof
    return best


def record_calls(page: Page, store: Store, project: Project, role: str, initiator: str, calls: list) -> None:
    """Store the JSON/API requests a screen made (method, status, fields) for the API tester. Calls to the
    portal's back end on another address (an api. sub-domain, another port) are kept by their full URL."""
    try:
        page.wait_for_load_state("networkidle", timeout=3000)
    except Exception:  # noqa: BLE001
        pass
    seen = set()
    for r in list(calls):
        try:
            req = r.request
            if not project.is_api_url(r.url):
                continue
            path = project.rel(r.url) if project.is_internal(r.url) else r.url.split("#")[0]
            if (req.method, path) in seen:
                continue
            seen.add((req.method, path))
            data = _json(r)
            shape, keys = _shape(data) if data is not None else ("", [])
            ctype = (r.headers.get("content-type") or "").split(";")[0]
            timing = r.request.timing or {}
            ms = int(timing.get("responseEnd", 0)) if timing.get("responseEnd", -1) > 0 else None
            store.insert("endpoints", {"role": role, "method": req.method, "path": path, "pattern": path_pattern(path),
                                       "status": r.status, "content_type": ctype, "keys": keys, "shape": shape,
                                       "initiator": initiator, "ms": ms, "source": "traffic", "documented": 0})
            live.emit("explorer", "request", f"{initiator} called {req.method} {path} -> HTTP {r.status}"
                      + (f" ({shape}; fields: {', '.join(keys[:6])})" if keys else ""), role=role, path=initiator,
                      api=path, status=r.status, level="bad" if r.status >= 500 else None)
        except Exception:  # noqa: BLE001
            continue


def load_openapi(project: Project) -> list[dict]:
    """GET operations from an OpenAPI file or URL (paths under api.prefix)."""
    import json as _j
    spec_ref = (project.cfg.get("api") or {}).get("openapi")
    if not spec_ref:
        return []
    try:
        if str(spec_ref).startswith(("http://", "https://", "/")) and not (project.root / str(spec_ref).lstrip("/")).exists():
            import httpx
            spec = httpx.get(project.url(spec_ref), timeout=15).json()
        else:
            text = (project.root / spec_ref).read_text(encoding="utf-8")
            if str(spec_ref).endswith((".yaml", ".yml")):
                import yaml
                spec = yaml.safe_load(text)
            else:
                spec = _j.loads(text)
    except Exception as exc:  # noqa: BLE001
        warn(f"could not read the OpenAPI description {spec_ref}: {exc}")
        return []
    prefix = (project.cfg.get("api") or {}).get("prefix") or "/"
    ops = []
    for path, item in (spec.get("paths") or {}).items():
        if not path.startswith(prefix) or not isinstance(item, dict) or "get" not in item:
            continue
        ops.append({"path": path, "pattern": re.sub(r"\{[^}]+\}", "{n}", path), "has_params": "{" in path,
                    "summary": (item["get"] or {}).get("summary") or ""})
    live.emit("explorer", "observe", f"Read the OpenAPI description: {len(ops)} GET operation(s) under {prefix}",
              openapi=str(spec_ref))
    return ops


def probe_openapi(page: Page, store: Store, project: Project, role: str, ops: list[dict]) -> None:
    """Call documented GET operations the screens did not use, so every API gets tested."""
    known = {r["pattern"] for r in store.all("SELECT pattern FROM endpoints WHERE role=?", [role])}
    for op in ops:
        if op["pattern"] in known:
            store.exec("UPDATE endpoints SET documented=1 WHERE role=? AND pattern=?", [role, op["pattern"]])
            continue
        if op["has_params"]:
            continue
        try:
            started = time.time()
            r = page.request.get(project.url(op["path"]), max_redirects=0)
            ms = int((time.time() - started) * 1000)
            data = _json(r)
            shape, keys = _shape(data) if data is not None else ("", [])
            store.insert("endpoints", {"role": role, "method": "GET", "path": op["path"], "pattern": op["pattern"],
                                       "status": r.status, "content_type": (r.headers.get("content-type") or "").split(";")[0],
                                       "keys": keys, "shape": shape, "initiator": None, "ms": ms, "source": "openapi",
                                       "documented": 1})
            live.emit("explorer", "request", f"Documented API GET {op['path']} -> HTTP {r.status} as {role}", role=role,
                      api=op["path"], status=r.status)
        except Exception:  # noqa: BLE001
            continue


def _same_origin(url: str, base: str) -> bool:
    a, b = urlparse(url), urlparse(base)
    return (a.scheme, a.netloc) == (b.scheme, b.netloc)


def explore(project: Project, store: Store, roles: list[str] | None = None) -> dict:
    ex = project.cfg["explore"]
    oracles = project.cfg["oracles"]
    exclude = [re.compile(p, re.I) for p in ex["exclude_patterns"]]
    roles = roles or list(project.roles())
    if ex.get("include_anonymous", True) and "anonymous" not in roles:
        roles = roles + ["anonymous"]
    from agentqa import testdata
    testdata.run_steps(project, "setup", "explore", agent="explorer")   # same starting data, same app map
    store.exec("DELETE FROM screens WHERE role IN (%s)" % ",".join("?" * len(roles)), roles)
    store.exec("DELETE FROM endpoints WHERE role IN (%s)" % ",".join("?" * len(roles)), roles)
    openapi = load_openapi(project) if project.cfg.get("api", {}).get("enabled", True) else []
    summary: dict[str, int] = {}
    otp_roles: set[str] = set()
    auth_profiles: dict[str, dict] = {}

    with sync_playwright() as pw:
        headed = os.environ.get("AGENTQA_HEADED") == "1"
        try:
            browser = pw.chromium.launch(headless=not headed and project.cfg["execution"].get("headless", True),
                                         slow_mo=int(os.environ.get("AGENTQA_SLOWMO", "0")) if headed else 0)
        except Exception:  # noqa: BLE001  (asked for a visible window where there is no screen: carry on headless)
            os.environ["AGENTQA_HEADED"] = "0"
            browser = pw.chromium.launch(headless=True)
        from agentqa import login_flow
        for role in roles:
            live.emit("explorer", "role", f"Exploring as {role}", role=role)
            state = None
            if role != "anonymous":
                log(f"  logging in as {role}")
                try:
                    state = login_flow.ensure_session(browser, project, role, "explorer")
                    if login_flow.session_used_otp(project, role):
                        otp_roles.add(role)
                except Exception as exc:  # noqa: BLE001
                    warn(f"login failed for {role}: {exc}")
                    live.emit("explorer", "issue", f"Login failed for {role}: {exc}", role=role, level="bad")
                    continue
            ctx = browser.new_context(storage_state=str(state) if state else None)
            ctx.set_default_timeout(int(ex.get("timeout_ms", 15000)))
            page = ctx.new_page()
            console: list[str] = []
            calls: list = []
            started_calls: list = []
            page.on("console", lambda m: console.append(m.text[:300]) if m.type == "error" else None)
            page.on("request", lambda r: started_calls.append(r) if r.resource_type in ("xhr", "fetch") else None)
            page.on("response", lambda r: calls.append(r) if r.request.resource_type in ("xhr", "fetch") else None)
            page.on("pageerror", lambda e: console.append(f"pageerror: {str(e)[:300]}"))

            # each role explores its own application; the anonymous visitor explores the public pages of every one
            apps = list(project.applications()) if role == "anonymous" else [project.app_of(role)]
            allowed_apps = set(apps)
            queue = deque((project.url(p, a), None, 0) for a in apps
                          for p in (project.applications()[a]["start_paths"] or ex["start_paths"]))
            seen: set[str] = set()
            explored: set[str] = set()
            store.exec("DELETE FROM journeys WHERE role=?", [role])
            skipped_note = False
            per_pattern: dict[str, int] = {}
            count = 0
            # pages a person showed AgentQA on an earlier run (deep screens the crawler could not reach on its own)
            replay_nav_hints(page, project, store, role, queue, seen)
            while queue and count < int(ex["max_pages_per_role"]):
                if assist.paused(project):
                    nav_takeover(page, project, store, role, queue, seen, "exploring")
                url, parent, depth = queue.popleft()
                url = urldefrag(url)[0]
                if url in seen or not project.is_internal(url):
                    continue
                path = project.rel(url)
                if project.split_path(path)[0] not in allowed_apps or not project.in_scope(path):
                    continue            # another portal, or outside the configured testing scope
                seen.add(url)
                if any(p.search(path) for p in exclude):
                    if not skipped_note:
                        live.emit("explorer", "skip", f"Skipped {path}: matches an exclude pattern (never followed)",
                                  role=role, path=path)
                        skipped_note = True
                    continue
                pattern = path_pattern(path)
                if per_pattern.get(pattern, 0) >= int(ex["max_instances_per_pattern"]):
                    continue
                per_pattern[pattern] = per_pattern.get(pattern, 0) + 1
                console.clear()
                calls.clear()
                started_calls.clear()
                started = time.time()
                try:
                    resp = page.goto(url, wait_until="load")
                except Exception as exc:  # noqa: BLE001
                    warn(f"{role}: could not open {path}: {exc.__class__.__name__}")
                    continue
                load_ms = int((time.time() - started) * 1000)
                status = resp.status if resp else 0
                if status < 400:
                    language.ensure_english(page, project, agent="explorer", role=role)   # English first
                final = page.url
                final_path = project.rel(final).split("?")[0]
                if role != "anonymous" and project.is_login_path(final_path) and not project.is_login_path(path):
                    # bounced to login: protected page this role cannot reach, keep a record
                    pass
                try:
                    info = page.evaluate(PAGE_SCRIPT)
                except Exception as exc:  # noqa: BLE001
                    warn(f"{role}: could not read {path}: {exc.__class__.__name__}")
                    continue
                if started_calls or calls:
                    record_calls(page, store, project, role, path, calls)
                    if role != "anonymous":
                        auth_profiles[role] = api_auth_profile(page, project, role, calls, auth_profiles.get(role))
                low = info["body_text"].lower()
                server_error = int(status >= 500 or any(p in low for p in oracles["server_error_patterns"]))
                links = []
                new_links = 0
                for link in info["links"]:
                    href = urldefrag(link["href"])[0]
                    if not href.startswith("http"):
                        continue
                    if language.is_switch(link["text"], href):
                        continue                # a switch to another language is not part of the app: never follow it
                    links.append({"href": href, "text": link["text"]})
                    if project.is_internal(href) and href not in seen:
                        queue.append((href, path, depth + 1))
                        new_links += 1
                final_path = project.rel(final).split("?")[0]
                live.shot(page, "explorer", "navigate",
                          f"Opened {path}" + (f" (redirected to {final_path})" if final_path != path.split("?")[0] else ""),
                          role=role, path=path, parent=parent, depth=depth, status=status, load_ms=load_ms,
                          page_title=info["title"], links=len(links), queued=new_links, final=final_path,
                          level="bad" if server_error or status >= 400 else None)
                for fi, form in enumerate(info["forms"]):
                    labels = [f["label"] or f["name"] for f in form["fields"]][:12]
                    if not labels:
                        continue
                    loc = page.locator("form").nth(fi)
                    live.shot(page, "explorer", "observe", f"Found a form with {len(form['fields'])} field(s) on {path}",
                              loc, role=role, path=path, fields=labels)
                if server_error or status >= 400:
                    live.emit("explorer", "issue", f"{path} answered HTTP {status}" +
                              (" with server error text" if server_error else ""), role=role, path=path, level="bad")
                a11 = info["a11y"]
                if a11["img_no_alt"] or a11["inputs_no_label"]:
                    live.emit("explorer", "issue", f"{path}: {len(a11['img_no_alt'])} image(s) without alt, "
                              f"{len(a11['inputs_no_label'])} unlabelled input(s)", role=role, path=path, level="warn")
                store.insert("screens", {
                    "role": role, "path": path, "url": url, "status": status, "title": info["title"],
                    "headings": info["headings"], "links": links, "forms": info["forms"],
                    "buttons": info["buttons"], "a11y": info["a11y"], "console": list(console),
                    "load_ms": load_ms, "pattern": pattern, "server_error": server_error,
                    "final_url": final})
                count += 1
                if ex.get("click_buttons", True) and status < 400 and not server_error:
                    click_explore(page, project, store, role, final, project.rel(final).split("?")[0], queue, seen, explored,
                                  int(ex.get("max_clicks_per_page", 12)))
            if openapi:
                probe_openapi(page, store, project, role, openapi)
            summary[role] = count
            log(f"  {role}: {count} screen(s) mapped")
            live.emit("explorer", "summary", f"{role}: {count} screen(s) mapped", role=role, screens=count)
            ctx.close()
        browser.close()
    store.set_meta("explore", summary)
    store.set_meta("otp_roles", sorted(otp_roles))
    store.set_meta("api_auth", {r: p for r, p in auth_profiles.items() if p})
    for r, p in auth_profiles.items():
        if p:
            where = {"local": "the browser's local storage", "session": "the browser's session storage",
                     "cookie": "a cookie", "memory": "the page's memory only"}.get(p["source"], p["source"])
            live.emit("explorer", "observe", f"{r}'s screens send the API a {p['header']} header; its value comes from {where}"
                      + (f" (key {p['key']})" if p.get("key") else ""), role=r, level="warn" if p["source"] == "memory" else None)
    return summary

CLICK_SCAN = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none' && !e.closest('[hidden]'); };
  const out = []; let n = 0;
  const sel = 'button, [role=button], [role=menuitem], [role=tab], [onclick], [aria-expanded], summary, a[href^="#"], a[href^="javascript"], a:not([href])';
  for (const e of document.querySelectorAll(sel)) {
    if (!vis(e) || e.disabled) continue;
    const form = e.closest('form');
    const submit = form && ((e.tagName === 'BUTTON' && (e.getAttribute('type') || 'submit') === 'submit') || (e.tagName === 'INPUT' && e.type === 'submit'));
    if (submit) continue;                                   // submitting forms is the Designer's job, not exploration
    if (form && form.querySelector('input:not([type=hidden]), select, textarea') && !e.getAttribute('aria-expanded')) continue;
    const t = (e.innerText || e.value || e.getAttribute('aria-label') || e.title || '').trim().replace(/\s+/g, ' ');
    if (!t || t.length > 40) continue;
    const id = 'x' + (n++); e.setAttribute('data-aq-x', id);
    out.push({id, text: t, tag: e.tagName.toLowerCase(), role: e.getAttribute('role') || '', chrome: !!e.closest('header, nav, [role=navigation], [role=banner]')});
  }
  return out;
}"""
VIEW_JS = r"""() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none' && !e.closest('[hidden]'); };
  const items = [...document.querySelectorAll('a[href], button, [role=button], [role=menuitem], [role=tab], input, select, textarea, [role=dialog], dialog[open]')]
    .filter(vis).map(e => (e.tagName + ':' + (e.innerText || e.value || e.getAttribute('aria-label') || e.name || '').trim().slice(0, 40)));
  return {url: location.href, items, dialog: [...document.querySelectorAll('[role=dialog], dialog[open], .modal.show')].some(vis)};
}"""
DANGER = re.compile(r"\b(log\s?-?out|sign\s?-?out|delete|remove|destroy|cancel|close|reject|approve|verify|withdraw|pay|"
                    r"submit|save|confirm|deactivate|transfer|print|download|export|reset|clear|x)\b|^\W*$|^×$", re.I)


def click_explore(page, project: Project, store: Store, role: str, url: str, path: str, queue, seen: set,
                  explored: set, limit: int = 12) -> int:
    """Click the buttons, menus and tabs on a page the way a tester does, and note what each one does.

    A click that changes the address adds that page to the crawl. A click that opens a menu, dialog or
    tab panel is followed one level deeper (Services > Apply for Certificate, Login > Citizen Login).
    A click that does nothing visible is recorded too: the functional tests check it later.
    Header and menu buttons are tried once per role, not on every page."""
    try:
        cands = page.evaluate(CLICK_SCAN)
    except Exception:  # noqa: BLE001
        return 0
    done = 0
    for c in cands:
        key = ("chrome:" if c["chrome"] else path + ":") + c["text"].lower()
        if key in explored or DANGER.search(c["text"]) or language.is_switch(c["text"]):
            continue
        explored.add(key)
        if done >= limit:
            break
        done += 1
        try:
            if page.url != url:
                page.goto(url, wait_until="load")
            before = page.evaluate(VIEW_JS)
            el = None
            fresh = page.evaluate(CLICK_SCAN)
            target = next((x for x in fresh if x["text"] == c["text"]), None)
            if not target:
                continue
            el = page.locator(f'[data-aq-x="{target["id"]}"]').first
            live.shot(page, "explorer", "action", f"Clicked '{c['text']}' to see what it does", el, role=role, path=path)
            el.click(timeout=4000)
            try:
                page.wait_for_load_state("load", timeout=6000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(400)
            after = page.evaluate(VIEW_JS)
        except Exception as exc:  # noqa: BLE001
            store.insert("journeys", {"role": role, "from_path": path, "action": "click", "target": c["text"], "kind": "error",
                                      "to_path": None, "title": None, "detail": {"error": str(exc)[:200]}, "created_at": now()})
            continue
        to_path = project.rel(after["url"])
        if after["url"].split("#")[0] != url.split("#")[0]:
            store.insert("journeys", {"role": role, "from_path": path, "action": "click", "target": c["text"], "kind": "navigate",
                                      "to_path": to_path, "title": page.title(), "detail": {}, "created_at": now()})
            live.emit("explorer", "observe", f"'{c['text']}' opens {to_path}", role=role, path=path)
            if after["url"] not in seen and project.is_internal(after["url"]):
                queue.append((after["url"], path, 1))
            continue
        revealed = [x for x in after["items"] if x not in before["items"]]
        if not revealed:
            store.insert("journeys", {"role": role, "from_path": path, "action": "click", "target": c["text"], "kind": "none",
                                      "to_path": path, "title": None, "detail": {}, "created_at": now()})
            live.emit("explorer", "observe", f"'{c['text']}' changed nothing visible on {path}", role=role, path=path)
            continue
        names = [x.split(":", 1)[1] for x in revealed if x.split(":", 1)[1]]
        store.insert("journeys", {"role": role, "from_path": path, "action": "click", "target": c["text"],
                                  "kind": "dialog" if after["dialog"] and not before["dialog"] else "reveal", "to_path": path,
                                  "title": None, "detail": {"revealed": names[:20]}, "created_at": now()})
        live.shot(page, "explorer", "observe", f"'{c['text']}' shows {', '.join(names[:5]) or 'more content'}", role=role, path=path)
        # one level deeper: the items the click revealed
        for inner in [n for n in names if n and not DANGER.search(n)][:8]:
            try:
                page.goto(url, wait_until="load")
                fresh = page.evaluate(CLICK_SCAN)
                opener = next((x for x in fresh if x["text"] == c["text"]), None)
                if not opener:
                    break
                page.locator(f'[data-aq-x="{opener["id"]}"]').first.click(timeout=4000)
                page.wait_for_timeout(300)
                inner_loc = page.get_by_text(inner, exact=True).first
                if not inner_loc.count() or not inner_loc.is_visible():
                    continue
                href = inner_loc.get_attribute("href")
                live.shot(page, "explorer", "action", f"Clicked '{c['text']}' > '{inner}'", inner_loc, role=role, path=path)
                inner_loc.click(timeout=4000)
                try:
                    page.wait_for_load_state("load", timeout=6000)
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(300)
                now_url = page.url
            except Exception:  # noqa: BLE001
                continue
            if now_url.split("#")[0] != url.split("#")[0]:
                tp = project.rel(now_url).split("?")[0]
                store.insert("journeys", {"role": role, "from_path": path, "action": "click", "target": f"{c['text']} > {inner}",
                                          "kind": "navigate", "to_path": tp, "title": page.title(), "detail": {"href": href},
                                          "created_at": now()})
                live.emit("explorer", "observe", f"'{c['text']} > {inner}' opens {tp}", role=role, path=path)
                if now_url not in seen and project.is_internal(now_url):
                    queue.append((now_url, path, 1))
    try:
        if page.url != url:
            page.goto(url, wait_until="load")
    except Exception:  # noqa: BLE001
        pass
    return done


# ---------------------------------------------------------------------------
# navigation help: the person takes over and shows the Explorer where to go
# ---------------------------------------------------------------------------

def _nav_steps(events: list[dict]) -> list[dict]:
    """A person's take-over actions as replayable navigation steps (clicks and typed values; no credentials)."""
    steps: list[dict] = []
    for ev in events or []:
        el = ev.get("el") or {}
        kind = ev.get("kind")
        if kind == "goto" and ev.get("path"):
            steps.append({"open": ev["path"]})
            continue
        if kind == "click":
            if el.get("tag") in ("input", "textarea", "select") and el.get("type") not in ("submit", "button"):
                continue
            text = (el.get("text") or el.get("aria") or el.get("title") or "").strip()
            if text and len(text) <= 60:
                steps.append({"click": text})
            elif el.get("href"):
                steps.append({"open": el["href"]})
        elif kind in ("input", "select"):
            val = str(ev.get("value") or "")
            if val and el.get("type") not in ("password",):
                steps.append({"type": val, "name": el.get("name") or "", "label": el.get("label") or el.get("placeholder") or ""})
        elif kind == "key" and ev.get("key") == "Enter":
            steps.append({"press": "Enter"})
    return steps


def _queue_internal(project: Project, store: Store, role: str, allowed, url: str, seen: set, queue, parent: str,
                    front: bool = False) -> bool:
    """Add a URL a person reached to the crawl (and note the journey), when it is in scope and not yet seen.
    Pages a person pointed at go to the front: they are mapped before the crawler's own finds."""
    url = urldefrag(url)[0]
    if not project.is_internal(url) or url in seen or any(x[0] == url for x in queue):
        return False
    path = project.rel(url)
    if project.split_path(path)[0] not in allowed or not project.in_scope(path):
        return False
    (queue.appendleft if front else queue.append)((url, parent, 1))
    store.insert("journeys", {"role": role, "from_path": parent, "action": "shown", "target": "you showed the way",
                              "kind": "navigate", "to_path": path, "title": None, "detail": {}, "created_at": now()})
    return True


def nav_takeover(page, project: Project, store: Store, role: str, queue, seen: set, where: str) -> None:
    """Paused during exploration: hand the browser to the person. Every internal page they open is added to the
    crawl, and the path they took is saved so the Explorer can reach that page by itself next time."""
    allowed = {project.app_of(role)} if role != "anonymous" else set(project.applications())
    start = page.url
    res = assist.takeover(project, page, role=role, agent="explorer",
                          question=f"Paused while {where} as {role}: you have the browser",
                          hint="Click through to any screen AgentQA has not reached (open a menu, search, pick a record). "
                               "Every page you open is added to the map, and AgentQA remembers the way for next time. "
                               "Press Continue when you are done.")
    if not res:
        return
    events = res.get("events") or []
    added = 0
    for ev in events:
        u = ev.get("url")
        if u and _queue_internal(project, store, role, allowed, u, seen, queue, project.rel(start)):
            added += 1
    landed = res.get("url") or page.url
    if project.is_internal(landed) and landed not in seen:
        if _queue_internal(project, store, role, allowed, landed, seen, queue, project.rel(start)):
            added += 1
    steps = _nav_steps(events)
    if steps and project.is_internal(landed):
        try:
            project.vault.add_nav_hint(role, project.rel(landed).split("?")[0], steps)
        except Exception as exc:  # noqa: BLE001
            warn(f"[explore] could not save the way you showed for {role}: {exc}")
    live.emit("explorer", "action", f"You showed {added} new page(s); added to the map and remembered", role=role,
              level="ok")


def replay_nav_hints(page, project: Project, store: Store, role: str, queue, seen: set) -> None:
    """Follow the navigation a person showed on an earlier run, to reach deep pages the crawler cannot find."""
    try:
        hints = project.vault.nav_hints(role) if project.vault.path.exists() else []
    except Exception:  # noqa: BLE001
        return
    allowed = {project.app_of(role)} if role != "anonymous" else set(project.applications())
    for hint in hints:
        steps = hint.get("steps") or []
        try:
            start = project.login_start(role) if role != "anonymous" else "/"
            page.goto(project.url(start), wait_until="load")
            language.ensure_english(page, project, agent="explorer", role=role)
            _replay_nav(page, project, steps)
            landed = page.url
            if _queue_internal(project, store, role, allowed, landed, seen, queue, start, front=True):
                live.emit("explorer", "observe", f"Reached {project.rel(landed)} the way you showed me", role=role)
        except Exception as exc:  # noqa: BLE001
            live.emit("explorer", "observe", f"Could not retrace the way to {hint.get('to')} ({exc.__class__.__name__}); "
                      "pause and show me again if it still matters", role=role, level="warn")


def _replay_nav(page, project: Project, steps: list[dict]) -> None:
    for st in steps:
        if "open" in st:
            page.goto(project.url(st["open"]) if not str(st["open"]).startswith("http") else st["open"], wait_until="load")
        elif "click" in st:
            loc = page.get_by_text(st["click"], exact=True)
            (loc.first if loc.count() else page.get_by_role("link", name=st["click"]).first).click(timeout=6000)
        elif "type" in st:
            sel = f'[name="{st["name"]}"]' if st.get("name") else None
            (page.locator(sel).first if sel else page.get_by_label(st.get("label") or "", exact=False).first).fill(st["type"])
        elif "press" in st:
            page.keyboard.press(st["press"])
        try:
            page.wait_for_load_state("load", timeout=6000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(200)


def teach_nav(project: Project, store: Store, role: str) -> dict:
    """Show AgentQA around as a role: log in, hand over the browser so the person opens the screens that matter,
    remember the way, then map everything (the normal crawl plus the pages the person showed)."""
    from agentqa import login_flow
    with sync_playwright() as pw:
        headed = os.environ.get("AGENTQA_HEADED") == "1"
        try:
            browser = pw.chromium.launch(headless=not headed, slow_mo=int(os.environ.get("AGENTQA_SLOWMO", "0")) if headed else 0)
        except Exception:  # noqa: BLE001  (no screen here: the box in the dashboard is enough)
            os.environ["AGENTQA_HEADED"] = "0"
            browser = pw.chromium.launch(headless=True)
        state = login_flow.ensure_session(browser, project, role, "explorer") if role != "anonymous" else None
        ctx = browser.new_context(storage_state=str(state) if state else None)
        page = ctx.new_page()
        start = project.login_start(role) if role != "anonymous" else "/"
        page.goto(project.url(start), wait_until="load")
        queue: deque = deque()
        seen: set = set()
        assist.request_pause(project)
        nav_takeover(page, project, store, role, queue, seen, "showing me around")
        assist.clear_pause(project)
        browser.close()
    shown = len(project.vault.nav_hints(role))
    # map the role afresh: the normal crawl, plus the pages just shown (replayed from the saved hints)
    explore(project, store, roles=[role])
    return {"shown": shown}


def probe_page(project: Project, role: str, path: str) -> dict | None:
    """Re-read one page (used by the Healer)."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        state = project.auth_file(role)
        ctx = browser.new_context(storage_state=str(state) if role != "anonymous" and state.exists() else None)
        page = ctx.new_page()
        try:
            page.goto(project.url(path), wait_until="load")
            live.shot(page, "healer", "navigate", f"Re-opened {path} as {role}", role=role, path=path)
            return page.evaluate(PAGE_SCRIPT)
        except Exception:  # noqa: BLE001
            return None
        finally:
            browser.close()
