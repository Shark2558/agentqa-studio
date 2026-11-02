"""AgentQA runtime: deterministic helpers used by the generated tests.

No AI model is called here, except by the two step kinds a recorded step cannot express: 'intent' (do what a
tester describes) and 'verify' (judge an expected result), which go to the Visual QA agent. A failure that starts with "DEFECT:" means the
application behaved differently from the expected result; any other error
(for example a missing locator) means the test itself may need healing.
"""
from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

import agentqa_live as live

SETTINGS = json.loads((Path(__file__).parent / "agentqa_settings.json").read_text(encoding="utf-8"))
ORACLES = SETTINGS["oracles"]
_WJS = Path(__file__).parent / "agentqa_widgets.js"
WIDGET_JS = _WJS.read_text(encoding="utf-8") if _WJS.exists() else "() => null"
STARTED = time.time()


class LocatorMissing(LookupError):
    """The page no longer has an element the test expects (a test issue, not a defect)."""


VERIFIED = {"n": 0}       # expected outcomes checked in the current test: a test that checked none does not pass
LOG: list[dict] = []      # the current test's steps, with times, for its evidence file


def step_log(kind: str, text: str, page=None, ev: dict | None = None) -> None:
    entry = {"t": round(time.time(), 3), "kind": kind, "text": str(text)[:400]}
    try:
        if page is not None:
            entry["url"] = page.url
    except Exception:  # noqa: BLE001
        pass
    if ev and ev.get("shot"):
        entry["shot"] = ev["shot"]
    LOG.append(entry)


def blocked(reason: str) -> None:
    """A precondition (usually a login) could not be met: the test is Blocked, never Passed."""
    import pytest
    step_log("blocked", reason)
    live.emit("executor", "verdict", "BLOCKED: " + reason, level="warn")
    pytest.skip("BLOCKED: " + reason)


def not_run(reason: str) -> None:
    import pytest
    step_log("not-run", reason)
    live.emit("executor", "verdict", "NOT RUN: " + reason, level="warn")
    pytest.skip("NOT RUN: " + reason)


def _ctx(page) -> dict:
    return {"case": getattr(page, "_aq_case", None), "role": getattr(page, "_aq_role", None)}


def defect(message: str, page=None) -> None:
    ctx = _ctx(page) if page is not None else {}
    ev = None
    if page is not None:
        ev = live.shot(page, "executor", "verdict", "DEFECT: " + message, level="bad", **ctx)
    else:
        live.emit("executor", "verdict", "DEFECT: " + message, level="bad")
    step_log("defect", message, page, ev)
    raise AssertionError("DEFECT: " + message)


def passed(page, message: str) -> None:
    """An expected outcome was checked and held."""
    VERIFIED["n"] += 1
    ev = live.emit("executor", "verdict", message, level="ok", **_ctx(page))
    step_log("verified", message, page, ev)


# several portals: a path on another application than the first is written '@<app>/path'
APPS = SETTINGS.get("apps") or {"main": {"base_url": SETTINGS["base_url"], "login_url": SETTINGS["login_url"]}}
PRIMARY = SETTINGS.get("primary_app") or next(iter(APPS))


def split_path(path: str) -> tuple[str, str]:
    if path.startswith("@"):
        app, _, rest = path[1:].partition("/")
        if app in APPS:
            return app, "/" + rest
    return PRIMARY, path


def url(path: str) -> str:
    if path.startswith("http"):
        return path
    app, p = split_path(path)
    return APPS[app]["base_url"] + p


def is_login(path: str) -> bool:
    app, p = split_path(path)
    return p.startswith(APPS[app].get("login_url") or "/login")


def body(page) -> str:
    try:
        return re.sub(r"\s+", " ", page.inner_text("body")).lower()
    except Exception:  # noqa: BLE001
        return ""


def alerts(page) -> list[str]:
    try:
        texts = page.locator("[role=alert], .error, .invalid-feedback, .alert-danger, .field-error").all_inner_texts()
        return [t.strip() for t in texts if t.strip()][:6]
    except Exception:  # noqa: BLE001
        return []


LANG = SETTINGS.get("language") or {}
LANG_DETECT = r"""() => { const t = (document.body ? document.body.innerText : '').slice(0, 5000);
  const l = (t.match(/\p{L}/gu) || []).length, a = (t.match(/[A-Za-z]/g) || []).length;
  return {lang: (document.documentElement.getAttribute('lang') || '').toLowerCase(), letters: l, ratio: l ? a / l : 1}; }"""
LANG_FIND = r"""(words) => { const want = new Set(words.map(w => w.toLowerCase()));
  for (const e of document.querySelectorAll('a, button, [role=button], [role=menuitem], [role=option], [onclick], li, span')) {
    const r = e.getBoundingClientRect(); if (r.width < 2 || r.height < 2) continue;
    const t = (e.innerText || e.value || e.getAttribute('aria-label') || e.title || '').trim().replace(/\s+/g, ' ');
    const href = e.getAttribute('href') || '';
    if (want.has(t.toLowerCase()) || /[?&](lang|language|locale|hl)=en\b|\/(lang|language|locale)\/en\b/i.test(href)) {
      if (/^(SPAN|LI)$/.test(e.tagName) && e.querySelector('a, button')) continue;
      e.setAttribute('data-aq-lang', '1'); return t; } }
  for (const s of document.querySelectorAll('select')) { const o = [...s.options].find(o => want.has(o.text.trim().toLowerCase()) || /^en(-|_|$)/i.test(o.value));
    if (o && s.selectedIndex !== o.index) { s.value = o.value; s.dispatchEvent(new Event('change', {bubbles: true})); return 'select:' + o.text; } }
  return null; }"""


def _is_english(info: dict) -> bool:
    lang, ratio, target = info.get("lang") or "", info.get("ratio", 1), LANG.get("target", "en")
    if lang and not lang.startswith(target) and ratio < 0.97:
        return False
    if info.get("letters", 0) >= 40:
        return ratio >= 0.75
    return not lang or lang.startswith(target)


def ensure_english(page) -> None:
    """English first: a page in another language is switched with the control AgentQA found (or a person showed)."""
    if not LANG.get("switch", True):
        return
    try:
        if _is_english(page.evaluate(LANG_DETECT)):
            return
        before = page.url
        app = split_path(_path(before))[0]
        words = list(LANG.get("words") or ["English", "ENG", "EN"])
        known = (LANG.get("learned") or {}).get(app) or {}
        if known.get("click"):
            words = [known["click"]] + words
        how = page.evaluate(LANG_FIND, words)
        if not how:
            step_log("observe", f"{_path(before)} is not in English and no language switch was found")
            return
        if not how.startswith("select:"):
            page.locator('[data-aq-lang="1"]').first.click(timeout=8000)
        page.wait_for_load_state("load")
        page.wait_for_timeout(200)
        if page.url.split("?")[0] != before.split("?")[0]:
            page.goto(before, wait_until="load")
        step_log("action", f"Switched the page to English ('{how.replace('select:', '')}')", page)
    except Exception as exc:  # noqa: BLE001
        step_log("observe", f"Could not switch the page to English: {exc.__class__.__name__}")


def goto(page, path: str) -> tuple[int, int]:
    started = time.time()
    resp = page.goto(url(path), wait_until="load")
    if resp is None or resp.status < 400:
        ensure_english(page)
    status, ms = (resp.status if resp else 0), int((time.time() - started) * 1000)
    final = _path(page.url)
    ev = live.shot(page, "executor", "navigate", f"Opened {path}" + (f" -> {final}" if final.split("?")[0] != path.split("?")[0] else "")
                   + f" (HTTP {status}, {ms} ms)", path=path, status=status, load_ms=ms,
                   level="bad" if status >= 400 else None, **_ctx(page))
    step_log("action", f"Opened {path} (HTTP {status}, {ms} ms)", page, ev)
    return status, ms


def _path(u: str) -> str:
    for app, a in sorted(APPS.items(), key=lambda x: -len(x[1]["base_url"])):
        base = a["base_url"]
        if u == base or u.startswith(base + "/") or u.startswith(base + "?"):
            rest = u[len(base):] or "/"
            return rest if app == PRIMARY else f"@{app}{rest}"
    p = urlparse(u)
    return p.path + (("?" + p.query) if p.query else "")


def short(value: str, n: int = 40) -> str:
    return value if len(value) <= n else f"{value[:n]}... ({len(value)} chars)"


# ---------------------------------------------------------------------------
# Pages, links, access
# ---------------------------------------------------------------------------

def check_page(page, path: str, max_load_ms: int | None = None) -> None:
    status, ms = goto(page, path)
    text = body(page)
    problems = []
    if status >= 400:
        problems.append(f"HTTP {status}")
    leaked = [p for p in ORACLES["server_error_patterns"] if p in text]
    if leaked:
        problems.append(f"server error text on page ({leaked[0]!r})")
    if max_load_ms and ms > max_load_ms:
        problems.append(f"took {ms} ms to load (limit {max_load_ms} ms)")
    errors = getattr(page, "console_errors", [])
    if errors and SETTINGS.get("console_errors_fail"):
        problems.append(f"{len(errors)} browser console error(s): {errors[0][:120]}")
    if problems:
        defect(f"{path}: " + "; ".join(problems), page)
    passed(page, f"{path} loaded cleanly in {ms} ms")


def check_links(page, links: list[dict]) -> None:
    broken = []
    for link in links:
        try:
            resp = page.request.get(url(link["href"]), max_redirects=5)
            live.emit("executor", "request", f"GET {link['href']} -> HTTP {resp.status}", path=link["href"],
                      status=resp.status, level="bad" if resp.status >= 400 else None, **_ctx(page))
            if resp.status >= 400:
                broken.append(f"{link['href']} -> HTTP {resp.status} (linked from {link['on']})")
        except Exception as exc:  # noqa: BLE001
            broken.append(f"{link['href']} -> {exc.__class__.__name__} (linked from {link['on']})")
    if broken:
        defect(f"{len(broken)} broken link(s): " + "; ".join(broken), page)
    passed(page, f"All {len(links)} internal link(s) opened")


def _not_found(status: int, text: str) -> bool:
    """A page that does not exist for this caller (404, or a 'not found'/'does not exist' message): they cannot
    reach it, which satisfies an access-denied check without being a wrong 200."""
    return status == 404 or (status < 400 and any(p in text for p in (
        "page not found", "not found", "does not exist", "no such page", "404")))


def check_access_denied(page, path: str, role: str) -> None:
    status, _ = goto(page, path)
    final = _path(page.url)
    text = body(page)
    bounced = is_login(final) and not is_login(path)
    told = any(p in text for p in ORACLES["denied_patterns"])
    nf = _not_found(status, text)
    if status in (401, 403) or bounced or told or nf:
        passed(page, f"Blocked as expected: {role} got " + (f"HTTP {status}" if status in (401, 403) else
                     "sent to login" if bounced else "a not-found page (the screen is not reachable)" if nf
                     else "an access-denied message"))
        return
    who = "An anonymous visitor" if role == "anonymous" else f"Role '{role}'"
    defect(f"{who} opened {path} (HTTP {status}, ended on {final}); access should be denied", page)


# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------

def _form(page, form: int, form_id: str | None):
    if form_id:
        loc = page.locator(f"form#{form_id}")
        if loc.count():
            return loc.first
    loc = page.locator("form")
    if loc.count() <= form:
        raise LocatorMissing(f"form #{form} not found on {_path(page.url)}")
    return loc.nth(form)


def _field(scope, name: str):
    loc = scope.locator(f'[name="{name}"]')
    if loc.count() == 0:
        raise LocatorMissing(f"field '{name}' not found")
    return loc.first


def _page_of(scope):
    return getattr(scope, "page", None) or scope


FILE_TOKEN = re.compile(r"^@file:([^:]+)(?::(\d+))?$")


def make_file(name: str, kb: int | None = None) -> Path:
    """A small, real file of the given type (PDF, PNG, JPG, other) padded to `kb` kilobytes."""
    import tempfile
    folder = Path(tempfile.gettempdir()) / "agentqa_uploads"
    folder.mkdir(exist_ok=True)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else "bin"
    size = int(kb or 20) * 1024
    target = folder / f"{size // 1024}k_{name}"
    if target.exists() and target.stat().st_size == size:
        return target
    if ext == "pdf":
        head = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\n"
                b"trailer<</Root 1 0 R>>\n")
        tail = b"%%EOF\n"
        filler = size - len(head) - len(tail)
        data = head + (b"%" + b"0" * 78 + b"\n") * max(0, filler // 80) + b"%" * max(0, filler % 80) + tail
    elif ext in ("png", "jpg", "jpeg", "gif", "bmp"):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (29, 78, 216)).save(buf, {"jpg": "JPEG", "jpeg": "JPEG"}.get(ext, ext.upper()))
        data = buf.getvalue()
        data += b"\0" * max(0, size - len(data))
    elif ext in ("exe", "dll", "bin"):
        data = b"MZ" + b"\0" * (size - 2)
    else:
        line = b"AgentQA test file\n"
        data = (line * (size // len(line) + 1))[:size]
    target.write_bytes(data[:max(size, len(data))] if ext in ("png", "jpg", "jpeg", "gif", "bmp") else data[:size])
    return target


def _date_for(value: str, placeholder: str) -> str:
    """Show an ISO date (YYYY-MM-DD) the way the widget expects it, e.g. DD/MM/YYYY from its placeholder."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value or "")
    fmt = (placeholder or "").upper()
    if not m or not re.search(r"DD|MM|YY", fmt):
        return value
    y, mo, d = m.groups()
    out = fmt.replace("YYYY", y).replace("YY", y[2:]).replace("MM", mo).replace("DD", d)
    return out


def _iso_from(value: str, placeholder: str) -> str | None:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
        return value
    fmt = (placeholder or "").upper()
    order = [t for t in re.findall(r"DD|MM|YYYY", fmt)]
    parts = re.findall(r"\d+", value or "")
    if len(order) == 3 and len(parts) == 3:
        got = dict(zip(order, parts))
        return f"{got['YYYY']}-{got['MM'].zfill(2)}-{got['DD'].zfill(2)}"
    return None


def _note(page, quiet: bool, title: str, el=None, **kw) -> None:
    """One step of form filling in Live View: with a screenshot, or (quiet) as a text step only.

    Fields that only carry valid background data are quiet, so a field test screenshots the field it
    is about, not all twelve others on every submission (a third of the run time on big forms)."""
    if quiet:
        live.emit("executor", "action", title, **kw)
    else:
        live.shot(page, "executor", "action", title, el, **kw)


def _set_widget(page, el, w: dict, value: str, name: str, shown: str, quiet: bool = False) -> str:
    ui = page.locator(f'[data-aq-ui="{w["ui"]}"]').first
    label = w.get("label") or name
    kind = w["kind"]
    if kind == "datepicker":
        text = _date_for(value, w.get("placeholder"))
        ui.evaluate("(e, v) => { e.removeAttribute('readonly'); e.value = v;"
                    " for (const t of ['input', 'change', 'blur']) e.dispatchEvent(new Event(t, {bubbles: true})); }", text)
        try:
            page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass
        if value and not el.input_value():
            iso = _iso_from(value, w.get("placeholder")) or value
            el.evaluate("(e, v) => { e.value = v; e.dispatchEvent(new Event('change', {bubbles: true})); }", iso)
        _note(page, quiet, f"Entered {label} as '{text}' in its date picker", ui, field=name, **_ctx(page))
        return text
    if kind == "richtext":
        ui.click()
        ui.evaluate("e => { const r = document.createRange(); r.selectNodeContents(e); const s = getSelection();"
                    " s.removeAllRanges(); s.addRange(r); }")
        page.keyboard.press("Delete")
        if value:
            page.keyboard.insert_text(value)
        ui.evaluate("e => { e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('blur')); }")
        if value and not el.input_value():
            el.evaluate("(e, v) => { e.value = v; }", value)
        _note(page, quiet, f"Typed '{shown}' into the {label} editor" if value else f"Cleared the {label} editor",
                  ui, field=name, **_ctx(page))
        return value
    if kind in ("listbox", "combobox"):
        wanted = [v for v in str(value).split("|") if v] if value else []
        texts = {o["value"]: o["text"] for o in (w.get("options") or [])}
        if el.evaluate("e => e.tagName") == "SELECT":
            texts.update({o["value"]: o["text"] for o in el.evaluate("e => [...e.options].map(o => ({value: o.value, text: o.text.trim()}))")})
        if kind == "combobox":
            ui.click()
            if wanted:
                page.keyboard.type(texts.get(wanted[0], wanted[0]))
                page.keyboard.press("Enter")
        else:
            opts = ui.locator("[role=option]")
            for i in range(opts.count()):
                o = opts.nth(i)
                val = o.get_attribute("data-value") or o.get_attribute("value") or o.inner_text().strip()
                on = o.get_attribute("aria-selected") == "true"
                want = val in wanted or o.inner_text().strip() in wanted
                if on != want:
                    o.click()
            missing = [v for v in wanted if v not in texts and v not in texts.values()]
            if missing:
                # a value the widget does not offer: set the hidden control directly so the server decides
                el.evaluate("(e, vs) => { if (e.tagName === 'SELECT') { for (const v of vs) { const o = document.createElement('option');"
                            " o.value = v; o.text = v; o.selected = true; e.appendChild(o); } } else { e.value = vs.join(','); } }", missing)
        shown_v = ", ".join(texts.get(v, v) for v in wanted) or "nothing"
        _note(page, quiet, f"Chose {shown_v} in {label}", ui, field=name, **_ctx(page))
        return shown_v
    ui.fill(value)
    _note(page, quiet, f"Typed '{shown}' into {label}", ui, field=name, **_ctx(page))
    return value


def set_value(scope, name: str, value, quiet: bool = False) -> None:
    el = _field(scope, name)
    page = _page_of(scope)
    info = el.evaluate("e => ({tag: e.tagName.toLowerCase(), type: (e.type || '').toLowerCase(), max: e.maxLength,"
                       " multiple: !!e.multiple,"
                       " hidden: (e.type || '').toLowerCase() === 'hidden' || !(e.offsetWidth || e.offsetHeight || e.getClientRects().length),"
                       " label: ((e.labels && e.labels[0] && e.labels[0].innerText) || e.getAttribute('aria-label')"
                       " || e.placeholder || e.name || '').trim().slice(0, 40)})")
    tag, ftype = info["tag"], info["type"]
    name_shown = info.get("label") or name
    value = "" if value is None else str(value)
    shown = live.mask(value, ftype, name)
    if ftype == "file":
        m = FILE_TOKEN.match(value)
        if m:
            f = make_file(m.group(1), int(m.group(2)) if m.group(2) else None)
            el.set_input_files(str(f))
            verb = f"Attached {m.group(1)} ({f.stat().st_size // 1024} KB) to {name_shown}"
        else:
            el.set_input_files([])
            verb = f"Left {name_shown} without a file"
        if hasattr(page, "screenshot"):
            _note(page, quiet, verb, el, field=name, **_ctx(page))
        return
    if info["hidden"] and hasattr(page, "keyboard"):
        w = el.evaluate(WIDGET_JS)
        if w:
            _set_widget(page, el, w, value, name, shown, quiet)
            return
        el.evaluate("(e, v) => { if (e.tagName === 'SELECT') { [...e.options].forEach(o => o.selected = v.split('|').includes(o.value)); }"
                    " else { e.value = v; } e.dispatchEvent(new Event('change', {bubbles: true})); }", value)
        live.emit("executor", "action", f"Set hidden {name} to '{shown}'", field=name, **_ctx(page))
        return
    if tag == "select":
        vals = [v for v in value.split("|") if v] if info["multiple"] else value
        try:
            el.select_option(value=vals)
        except Exception:  # noqa: BLE001
            el.select_option(label=vals)
        verb = f"Selected '{shown}' in {name_shown}" if value else f"Left {name_shown} unselected"
    elif ftype in ("checkbox", "radio"):
        el.check() if value else el.uncheck()
        verb = f"{'Ticked' if value else 'Unticked'} '{name_shown}'"
    elif (info["max"] and info["max"] > 0 and len(value) > info["max"]) or ftype == "date":
        # bypass client-side limits so the server's own validation is tested
        el.evaluate("(e, v) => { e.value = v; e.dispatchEvent(new Event('input', {bubbles: true}));"
                    " e.dispatchEvent(new Event('change', {bubbles: true})); }", value)
        verb = f"Set {name_shown} to '{shown}'" + (" (bypassing the form's own limit)" if ftype != "date" else "")
    else:
        el.fill(value)
        verb = f"Typed '{shown}' into {name_shown}" if value else f"Left {name_shown} empty"
    if hasattr(page, "screenshot"):
        _note(page, quiet, verb, el, field=name, **_ctx(page))


def submit(page, path: str, form: int, form_id: str | None, values: dict, focus: str | None = None) -> dict:
    goto(page, path)
    before = body(page)
    f = _form(page, form, form_id)
    for name, value in values.items():
        set_value(f, name, value, quiet=name != focus)
    if focus is None or focus not in values:
        live.shot(page, "executor", "action", f"Filled {len(values)} field(s) on {path} with valid values", f, **_ctx(page))
    f.evaluate("f => { f.noValidate = true; }")
    statuses: list[int] = []

    def on_response(resp):
        if resp.request.resource_type == "document":
            statuses.append(resp.status)

    page.on("response", on_response)
    btn = f.locator("button[type=submit], input[type=submit], button:not([type])")
    if btn.count():
        label = (btn.first.inner_text() or btn.first.get_attribute("value") or "Submit").strip()
        live.shot(page, "executor", "action", f"Clicked '{label}' (browser validation off, so the server decides)",
                  btn.first, **_ctx(page))
        btn.first.click()
    else:
        live.emit("executor", "action", "Submitted the form", **_ctx(page))
        f.evaluate("f => (f.requestSubmit ? f.requestSubmit() : f.submit())")
    page.wait_for_load_state("load")
    page.wait_for_timeout(120)
    page.remove_listener("response", on_response)
    after = body(page)
    status = statuses[-1] if statuses else 200

    def new(patterns):
        return [p for p in patterns if after.count(p) > before.count(p)]

    result = {"status": status, "url": _path(page.url), "success": new(ORACLES["success_patterns"]),
              "errors": new(ORACLES["error_patterns"]), "alerts": alerts(page),
              "server_error": status >= 500 or any(p in after for p in ORACLES["server_error_patterns"])}
    said = "; ".join(result["alerts"][:2]) or ("success message shown" if result["success"] else "no message")
    live.shot(page, "executor", "observe", f"Server answered HTTP {status}: {said}", status=status,
              accepted=bool(result["success"]), **_ctx(page))
    return result


def check_form_valid(page, path: str, form: int, form_id: str | None, values: dict) -> None:
    r = submit(page, path, form, form_id, values)
    if r["server_error"]:
        defect(f"valid submission on {path} caused a server error (HTTP {r['status']})", page)
    if not r["success"]:
        msg = "; ".join(r["alerts"]) or "no success message appeared"
        defect(f"valid submission on {path} was not accepted (HTTP {r['status']}): {msg}", page)
    passed(page, f"Valid submission accepted on {path}")


def check_field_rejects(page, path, form, form_id, base, field, label, values, descriptions, **_):
    accepted = []
    for value, desc in zip(values, descriptions):
        data = dict(base)
        data[field] = value
        r = submit(page, path, form, form_id, data, focus=field)
        if r["server_error"]:
            accepted.append(f"{desc}: server error HTTP {r['status']}")
        elif r["success"]:
            accepted.append(f"{desc} ({short(value)!r})")
    if accepted:
        defect(f"{label} accepted invalid input: " + "; ".join(accepted), page)
    passed(page, f"{label} rejected every invalid value: " + "; ".join(descriptions))


def check_field_accepts(page, path, form, form_id, base, field, label, values, descriptions, **_):
    rejected = []
    for value, desc in zip(values, descriptions):
        data = dict(base)
        data[field] = value
        r = submit(page, path, form, form_id, data, focus=field)
        if r["server_error"] or not r["success"]:
            rejected.append(f"{desc}: {'; '.join(r['alerts']) or 'HTTP ' + str(r['status'])}")
    if rejected:
        defect(f"{label} rejected a valid value: " + "; ".join(rejected), page)
    passed(page, f"{label} accepted: " + "; ".join(descriptions))


def check_attribute(page, path, form, form_id, field, label, attribute, expected, **_):
    goto(page, path)
    el = _field(_form(page, form, form_id), field)
    actual = el.get_attribute(attribute)
    live.shot(page, "executor", "observe", f"Inspected {label}: {attribute}={actual!r}", el, **_ctx(page))
    if str(actual) != str(expected):
        defect(f"{label}: the form sets {attribute}={actual!r}; expected {expected!r}", page)
    passed(page, f"{label}: {attribute}={actual!r} as expected")


def _sim(a: str, b: str) -> float:
    a, b = a.strip().lower(), b.strip().lower()
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()


def check_options(page, path, form, form_id, field, label, expected, **_):
    goto(page, path)
    el = _field(_form(page, form, form_id), field)
    opts = el.evaluate("e => [...e.options].filter(o => o.value.trim()).map(o => o.text.trim())")
    missing = [x for x in expected if max((_sim(x, o) for o in opts), default=0) < 0.8]
    extra = [o for o in opts if max((_sim(o, x) for x in expected), default=0) < 0.8]
    live.shot(page, "executor", "observe", f"Read {label} options: {', '.join(opts)}", el, **_ctx(page))
    if missing or extra:
        defect(f"{label} options are {opts}; expected {expected}"
               + (f"; missing {missing}" if missing else "") + (f"; unexpected {extra}" if extra else ""), page)
    passed(page, f"{label} options match the SRS")


A11Y_SCRIPT = r"""() => {
  const txt = el => (el ? (el.innerText || el.textContent || '').trim() : '');
  const labelled = e => (e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`)) || e.closest('label')
      || e.getAttribute('aria-label') || e.getAttribute('aria-labelledby') || e.getAttribute('title');
  const issues = [];
  const imgs = [...document.querySelectorAll('img')].filter(i => !i.hasAttribute('alt'));
  if (imgs.length) issues.push(`${imgs.length} image(s) without alt text`);
  const unl = [...document.querySelectorAll('input, select, textarea')]
    .filter(e => !['hidden','submit','button','reset','image'].includes((e.type || '').toLowerCase()))
    .filter(e => e.offsetWidth || e.offsetHeight || e.getClientRects().length)
    .filter(e => !labelled(e)).map(e => e.name || e.id || e.tagName.toLowerCase());
  if (unl.length) issues.push(`form control(s) without a label: ${unl.join(', ')}`);
  const btn = [...document.querySelectorAll('button, [role=button]')].filter(b => !txt(b) && !b.getAttribute('aria-label') && !b.getAttribute('title'));
  if (btn.length) issues.push(`${btn.length} button(s) without an accessible name`);
  if (!document.documentElement.getAttribute('lang')) issues.push('<html> has no lang attribute');
  if (!document.title.trim()) issues.push('page has no <title>');
  return issues;
}"""


AXE = Path(__file__).parent / "agentqa_axe.js"


def check_a11y(page, path: str) -> None:
    goto(page, path)
    a11y = SETTINGS.get("accessibility") or {}
    if a11y.get("engine", "axe") == "axe" and AXE.exists():
        page.add_script_tag(path=str(AXE))
        found = page.evaluate("""async (tags) => {
          const r = await axe.run(document, {runOnly: {type: 'tag', values: tags}, resultTypes: ['violations']});
          return r.violations.map(v => ({id: v.id, impact: v.impact || 'minor', help: v.help, nodes: v.nodes.length,
            targets: v.nodes.slice(0, 3).map(n => [].concat(n.target).join(' ')),
            wcag: v.tags.filter(t => /^wcag\\d/.test(t))}));
        }""", a11y.get("tags") or ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
        fail_on = set(a11y.get("fail_on") or ["critical", "serious"])
        bad = [v for v in found if v["impact"] in fail_on]
        minor = [v for v in found if v["impact"] not in fail_on]
        for v in found[:6]:
            sel = v["targets"][0] if v["targets"] else None
            loc = None
            try:
                loc = page.locator(sel).first if sel else None
            except Exception:  # noqa: BLE001
                loc = None
            live.shot(page, "executor", "observe", f"axe: {v['id']} ({v['impact']}) - {v['help']}", loc,
                      level="bad" if v in bad else "warn", **_ctx(page))
        if bad:
            defect(f"{path}: " + "; ".join(f"{v['id']} ({v['impact']}): {v['help']} - {v['nodes']} element(s), e.g. "
                                           f"{', '.join(v['targets'][:2])}" for v in bad), page)
        passed(page, f"{path} passed the WCAG 2.2 AA rules checked by axe"
               + (f" ({len(minor)} lower-impact note(s): {', '.join(v['id'] for v in minor)})" if minor else ""))
        return
    issues = page.evaluate(A11Y_SCRIPT)
    if issues:
        defect(f"{path}: " + "; ".join(issues), page)
    passed(page, f"{path} passed the basic accessibility checks")


# ---------------------------------------------------------------------------
# Multi-role workflows
# ---------------------------------------------------------------------------

CLICKABLE_JS = """() => [...document.querySelectorAll('button, a[href], [role=button], input[type=submit], input[type=button]')]
  .filter(e => e.offsetWidth || e.offsetHeight).map(e => (e.innerText || e.value || e.getAttribute('aria-label') || '').trim())
  .filter(Boolean).slice(0, 300)"""


def _heal_click(page, raw: str, vars_: dict) -> dict | None:
    """When a workflow click target is missing but the record is on screen, suggest the renamed control."""
    if not raw.startswith("text="):
        return None
    want_t = raw[5:]
    used = {k: v for k, v in vars_.items() if "{" + k + "}" in want_t and v}
    want = want_t.format(**vars_)
    cands = page.evaluate(CLICKABLE_JS)
    related = [c for c in cands if all(v in c for v in used.values())] if used else cands
    if not related:
        return None
    best = max(related, key=lambda c: _sim(c, want))
    if _sim(best, want) < 0.35 and not used:
        return None
    new_t = best
    for k, v in used.items():
        new_t = new_t.replace(v, "{" + k + "}")
    return {"key": "click", "old": raw, "new": "text=" + new_t, "offered": best}


def run_workflow(open_role, steps: list[dict]) -> None:
    vars_: dict[str, str] = {}
    started = time.time()

    def sub(text):
        return str(text).format(**vars_) if isinstance(text, str) else text

    for i, st in enumerate(steps, 1):
        role = st["role"]
        page = open_role(role)
        where = f"step {i} ({role})"
        live.emit("executor", "step", f"Workflow {where}", step=i, **_ctx(page))
        if st.get("goto"):
            status, _ = goto(page, sub(st["goto"]))
            if status >= 400:
                defect(f"{where}: {sub(st['goto'])} returned HTTP {status}", page)
        for name, value in (st.get("fill") or {}).items():
            set_value(page, name, sub(value))
        for name, value in (st.get("upload") or {}).items():
            set_value(page, name, value if str(value).startswith("@file:") else f"@file:{value}")
        if st.get("fill_otp"):
            set_value(page, st["fill_otp"], otp_for(role, since=started))
        if st.get("submit"):
            form = page.locator(sub(st["submit"])).first
            form.evaluate("f => { f.noValidate = true; }")
            btn = form.locator("button[type=submit], input[type=submit], button:not([type])")
            if btn.count():
                live.shot(page, "executor", "action", "Clicked submit", btn.first, **_ctx(page))
                btn.first.click()
            else:
                form.evaluate("f => f.requestSubmit()")
            page.wait_for_load_state("load")
            live.shot(page, "executor", "observe", f"{where}: submitted", **_ctx(page))
        if st.get("click"):
            target = page.locator(sub(st["click"]))
            if target.count() == 0:
                heal = _heal_click(page, st["click"], vars_)
                if heal:
                    heal["step"] = i
                    live.shot(page, "executor", "observe", f"{where}: '{sub(st['click'])}' is gone, but the screen offers "
                              f"'{heal['offered']}' for the same record: the control was probably renamed", level="warn",
                              **_ctx(page))
                    raise LocatorMissing(f"{where}: click target '{sub(st['click'])}' not found; the screen offers "
                                         f"'{heal['offered']}' [heal {json.dumps(heal)}]")
                defect(f"{where}: '{sub(st['click'])}' is not on {_path(page.url)} "
                       f"(the item did not reach this role's screen)", page)
            live.shot(page, "executor", "action", f"Clicked {sub(st['click'])}", target.first, **_ctx(page))
            target.first.click()
            page.wait_for_load_state("load")
        if st.get("expect_text"):
            if str(st["expect_text"]).lower() not in body(page):
                defect(f"{where}: expected text '{st['expect_text']}' not shown; page says: "
                       f"{'; '.join(alerts(page)) or body(page)[:160]}", page)
            passed(page, f"{where}: saw '{st['expect_text']}'")
        if st.get("expect_selector_text"):
            spec = st["expect_selector_text"]
            loc = page.locator(sub(spec["selector"]))
            if loc.count() == 0:
                defect(f"{where}: '{sub(spec['selector'])}' not found on {_path(page.url)}", page)
            actual = loc.first.inner_text().strip()
            live.shot(page, "executor", "observe", f"{where}: read '{actual}'", loc.first, **_ctx(page))
            if str(spec["text"]).lower() not in actual.lower():
                defect(f"{where}: expected '{spec['text']}', found '{actual}'", page)
            passed(page, f"{where}: status is '{actual}'")
        if st.get("expect_email"):
            spec = st["expect_email"] if isinstance(st["expect_email"], dict) else {"to": st["expect_email"]}
            to = sub(spec.get("to") or contact(role, "email"))
            m = wait_message(to, since=started, kind="email", contains=sub(spec.get("contains") or ""))
            if not m:
                defect(f"{where}: no email reached {to} (mock inbox {SETTINGS.get('inbox_url')})", page)
            passed(page, f"{where}: email to {to}: '{m['subject']}'")
        for var, selector in (st.get("capture") or {}).items():
            loc = page.locator(sub(selector))
            if loc.count() == 0:
                defect(f"{where}: could not read '{selector}' to capture {var}", page)
            vars_[var] = loc.first.inner_text().strip()
            live.emit("executor", "observe", f"{where}: remembered {var} = {vars_[var]}", **_ctx(page))


# ---------------------------------------------------------------------------
# APIs and record isolation
# ---------------------------------------------------------------------------

API_AUTH = SETTINGS.get("api_auth") or {}       # role -> how its screens authenticate API calls (from the Explorer)
_READ_TOKEN_JS = """([src, key]) => { const s = src === 'local' ? localStorage : sessionStorage; return s.getItem(key); }"""


def _dig(obj, path: list):
    for k in path:
        if isinstance(obj, dict):
            obj = obj.get(k)
        elif isinstance(obj, list) and isinstance(k, int) and k < len(obj):
            obj = obj[k]
        else:
            return None
    return obj


def _observed_auth(page, name: str, landing: str) -> str | None:
    """The value the portal's own screens send in the auth header: open the landing page and watch one API call.
    Works for tokens the page keeps only in memory."""
    found: list[str] = []

    def on_req(r):
        v = r.headers.get(name)
        if v and not found:
            found.append(v)
    page.on("request", on_req)
    try:
        page.goto(url(landing), wait_until="load")
        for _ in range(20):
            if found:
                break
            page.wait_for_timeout(250)
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            page.remove_listener("request", on_req)
        except Exception:  # noqa: BLE001
            pass
    return found[0] if found else None


def api_headers(page) -> dict:
    """The headers a logged-in role's screens send to the API (an Authorization header read from the place
    the Explorer saw it in), so API tests are made the way the portal itself makes them. {} when the portal
    uses cookies only, or the caller is anonymous."""
    cached = getattr(page, "_aq_api_headers", None)
    if cached is not None:
        return cached
    role = (getattr(page, "_aq_role", None) or "anonymous").split("__")[0]
    prof = API_AUTH.get(role) if role != "anonymous" else None
    headers: dict = {}
    if prof and prof.get("header"):
        name, src = prof["header"], prof.get("source")
        api_url = prof.get("api") or "/"
        app = split_path(api_url)[0] if not str(api_url).startswith("http") else PRIMARY
        landing = (SETTINGS.get("landing") or {}).get(role) or ("/" if app == PRIMARY else f"@{app}/")
        value = None
        if src in ("local", "session"):
            try:
                if page.url == "about:blank" or not page.url.startswith(APPS[app]["base_url"]):
                    page.goto(url(landing), wait_until="load")
                raw = page.evaluate(_READ_TOKEN_JS, [src, prof.get("key")])
                if raw is not None and prof.get("path"):
                    raw = _dig(json.loads(raw), prof["path"])
                if raw:
                    value = str(prof.get("prefix") or "") + str(raw)
            except Exception:  # noqa: BLE001
                value = None
        elif src == "cookie":
            cv = next((c["value"] for c in page.context.cookies() if c.get("name") == prof.get("key")), None)
            value = (str(prof.get("prefix") or "") + cv) if cv else None
        if not value:
            value = _observed_auth(page, name, landing)
        if not value:
            where = {"local": "the browser's local storage", "session": "the browser's session storage", "cookie": "a cookie",
                     "memory": "the page's memory"}.get(src, src)
            blocked(f"the {role} screens send the API a {name} header taken from {where}, but it could not be read from the "
                    f"saved {role} session; log in as {role} again (Test data page) and re-run")
        headers = {name: value}
    page._aq_api_headers = headers
    return headers


def _api(page, path: str):
    started = time.time()
    resp = page.request.get(url(path), max_redirects=0, fail_on_status_code=False, headers=api_headers(page) or None)
    ms = int((time.time() - started) * 1000)
    ctype = resp.headers.get("content-type", "")
    data = None
    if "json" in ctype:
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            data = None
    return resp.status, ms, data, resp


def _summary(data) -> str:
    if isinstance(data, list):
        first = next((x for x in data if isinstance(x, dict)), None)
        return f"a list of {len(data)}" + (f" with fields {', '.join(sorted(first)[:6])}" if first else "")
    if isinstance(data, dict):
        return f"fields {', '.join(sorted(data)[:8])}"
    return "a non-JSON body"


def _show(page, path: str, title: str, level=None) -> None:
    """Open the API address in the browser so Live View shows what came back."""
    try:
        page.goto(url(path), wait_until="load")
    except Exception:  # noqa: BLE001
        pass
    live.shot(page, "executor", "observe", title, path=path, level=level, **_ctx(page))


def check_api(page, path: str, keys: list, max_ms: int | None = None, **_) -> None:
    status, ms, data, _resp = _api(page, path)
    live.emit("executor", "request", f"GET {path} -> HTTP {status} in {ms} ms", path=path, status=status,
              level="bad" if status >= 400 else None, **_ctx(page))
    problems = []
    if status >= 400:
        problems.append(f"HTTP {status}")
    elif status >= 300:
        problems.append(f"redirected (HTTP {status}) instead of answering")
    else:
        got = None
        if keys and data is None:
            problems.append("did not return JSON")
        elif isinstance(data, dict):
            got = set(data)
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            got = set(data[0])
        if got is not None:
            missing = [k for k in keys if k not in got]
            if missing:
                problems.append(f"response is missing field(s) {', '.join(missing)} that the screens rely on")
        if max_ms and ms > max_ms:
            problems.append(f"took {ms} ms (limit {max_ms} ms)")
    _show(page, path, f"GET {path} returned {_summary(data)} (HTTP {status})", "bad" if problems else None)
    if problems:
        defect(f"GET {path}: " + "; ".join(problems), page)
    passed(page, f"GET {path} answered in {ms} ms with {_summary(data)}")


def _refused(status: int, resp) -> bool:
    loc = resp.headers.get("location", "")
    return status in (401, 403, 404) or (300 <= status < 400 and any((a.get("login_url") or "/login") in loc
                                                                       for a in APPS.values()))


def check_api_denied(page, path: str, role: str, **_) -> None:
    status, ms, data, resp = _api(page, path)
    who = "An anonymous caller" if role == "anonymous" else f"Role '{role}'"
    live.emit("executor", "request", f"GET {path} as {role} -> HTTP {status}", path=path, status=status,
              level=None if _refused(status, resp) else "bad", **_ctx(page))
    if _refused(status, resp):
        _show(page, path, f"Refused as expected: HTTP {status}")
        passed(page, f"GET {path} refused {role} (HTTP {status})")
        return
    _show(page, path, f"{who} received {_summary(data)}", "bad")
    if status >= 500:
        defect(f"GET {path} crashed with HTTP {status} for {role}", page)
    defect(f"{who} read GET {path} (HTTP {status}, {_summary(data)}); the API must refuse this role", page)


def check_record_isolation(open_role, path: str, owner: str, peer: str, **_) -> None:
    owner_page = open_role(owner)
    s1, _, d1, _r = _api(owner_page, path)
    live.emit("executor", "request", f"GET {path} as the first {owner} -> HTTP {s1}", path=path, status=s1,
              **_ctx(owner_page))
    if not 200 <= s1 < 300:
        raise LocatorMissing(f"the record {path} no longer opens for its owner (HTTP {s1}); refresh the test data")
    peer_page = open_role(peer)
    s2, _, d2, r2 = _api(peer_page, path)
    live.emit("executor", "request", f"GET {path} as a second {owner} -> HTTP {s2}", path=path, status=s2,
              level=None if _refused(s2, r2) else "bad", **_ctx(peer_page))
    if _refused(s2, r2):
        _show(peer_page, path, f"Second {owner} was refused (HTTP {s2})")
        passed(peer_page, f"A second {owner} cannot read {path} (HTTP {s2})")
        return
    same = d2 == d1 or (isinstance(d1, dict) and isinstance(d2, dict) and d1.get("id") is not None
                        and d1.get("id") == d2.get("id"))
    _show(peer_page, path, f"Second {owner} received {_summary(d2)}", "bad" if same else None)
    if same:
        shown = ", ".join(sorted(d2)[:10]) if isinstance(d2, dict) else _summary(d2)
        defect(f"A second {owner} account read {path}, a record that belongs to another user "
               f"(HTTP {s2}; fields exposed: {shown})", peer_page)
    passed(peer_page, f"A second {owner} gets different data from {path} (HTTP {s2})")


# ---------------------------------------------------------------------------
# Security basics
# ---------------------------------------------------------------------------

def check_security_headers(page, path: str = "/", **_) -> None:
    resp = page.request.get(url(path))
    h = {k.lower(): v for k, v in resp.headers.items()}
    https = SETTINGS["base_url"].startswith("https")
    csp = h.get("content-security-policy", "")
    missing = []
    if not csp:
        missing.append("Content-Security-Policy")
    if "x-frame-options" not in h and "frame-ancestors" not in csp:
        missing.append("X-Frame-Options (clickjacking protection)")
    if h.get("x-content-type-options", "").lower() != "nosniff":
        missing.append("X-Content-Type-Options: nosniff")
    if "referrer-policy" not in h:
        missing.append("Referrer-Policy")
    if https and "strict-transport-security" not in h:
        missing.append("Strict-Transport-Security")
    goto(page, path)
    live.shot(page, "executor", "observe", f"Read the response headers of {path}: "
              + (f"{len(missing)} missing" if missing else "all present"), level="bad" if missing else None, **_ctx(page))
    if missing:
        defect(f"Security headers missing on {path}: " + "; ".join(missing), page)
    passed(page, "All standard security headers are present")


def check_session(open_role, role: str, logout_url: str, protected: str, **_) -> None:
    auth = Path(os.environ.get("AGENTQA_AUTH_DIR", Path(__file__).parent.parent / ".agentqa" / "auth"))
    meta_file = auth / f"{role}__sec.meta.json"
    if not meta_file.exists():
        raise LocatorMissing("no dedicated security login was saved; re-run the Executor")
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    problems = []
    kept = [n for n, v in meta.get("before", {}).items() if meta.get("after", {}).get(n) == v]
    if kept:
        problems.append(f"the session cookie(s) {', '.join(kept)} kept the same value through login (session fixation)")
    page = open_role(f"{role}__sec")
    status, _ = goto(page, protected)
    if is_login(_path(page.url)):
        raise LocatorMissing(f"the saved security login could not open {protected}")
    goto(page, logout_url)
    live.shot(page, "executor", "action", f"Logged out through {logout_url}", **_ctx(page))
    ctx2 = page.context.browser.new_context(storage_state=str(auth / f"{role}__sec.json"))
    try:
        p2 = ctx2.new_page()
        p2._aq_case, p2._aq_role = getattr(page, "_aq_case", None), role
        resp = p2.goto(url(protected), wait_until="load")
        final = _path(p2.url)
        reused = not (is_login(final) or (resp and resp.status in (401, 403)))
        live.shot(p2, "executor", "observe", "Replayed the old session cookie after logout: "
                  + ("still logged in" if reused else "refused"), level="bad" if reused else None, **_ctx(p2))
        if reused:
            problems.append(f"after logout, a copy of the old session cookie still opens {protected}; "
                            f"the session is not ended on the server")
    finally:
        ctx2.close()
    if problems:
        defect("Session handling: " + "; ".join(problems), page)
    passed(page, "A new session is issued at login and logout ends it on the server")


def check_otp_single_use(page, role: str, **_) -> None:
    auth = Path(os.environ.get("AGENTQA_AUTH_DIR", Path(__file__).parent.parent / ".agentqa" / "auth"))
    meta_file = auth / f"{role}__otp.meta.json"
    if not meta_file.exists():
        raise LocatorMissing("no OTP login check was recorded; re-run the Executor")
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    if meta.get("error"):
        raise LocatorMissing(f"the OTP check could not run: {meta['error']}")
    live.emit("executor", "observe", f"Second login as {role} with the OTP from the first login: "
              + ("accepted" if meta.get("reused_accepted") else "refused"),
              level="bad" if meta.get("reused_accepted") else None, **_ctx(page))
    if meta.get("reused_accepted"):
        defect(f"a one-time password that was already used was accepted again for {role}: the second login with the "
               f"first login's OTP opened {meta.get('landed')}" + (" (the portal re-sent the same code)" if meta.get("same_code") else ""),
               page)
    passed(page, f"A used OTP is refused for {role}")


CSRF_NAMES = re.compile(r"csrf|xsrf|_token|authenticity|requestverificationtoken|nonce", re.I)


def check_csrf(open_role, forms: list, **_) -> None:
    unprotected, page = [], None
    for f in forms:
        page = open_role(f["role"])
        goto(page, f["path"])
        info = page.evaluate("""() => [...document.querySelectorAll('form')]
            .filter(f => (f.getAttribute('method') || 'get').toLowerCase() === 'post')
            .filter(f => !f.querySelector('input[type=password]'))
            .map(f => ({action: f.getAttribute('action') || location.pathname,
                        hidden: [...f.querySelectorAll('input[type=hidden]')].map(i => i.name)}))""")
        for form in info:
            if not any(CSRF_NAMES.search(n or "") for n in form["hidden"]):
                unprotected.append(f"{re.sub(r'/[0-9]+(?=/|$)', '/{id}', form['action'])} (on {f['path']})")
        live.shot(page, "executor", "observe", f"Checked {len(info)} data-changing form(s) on {f['path']} for an "
                  "anti-forgery token", **_ctx(page))
    if unprotected:
        cookies = page.context.cookies() if page else []
        samesite = sorted({(c.get("sameSite") or "None") for c in cookies})
        mitigated = samesite and all(x in ("Lax", "Strict") for x in samesite)
        defect(f"{len(dict.fromkeys(unprotected))} form(s) that change data have no anti-forgery token: "
               + "; ".join(dict.fromkeys(unprotected))
               + (f" (mitigated: session cookie is SameSite={'/'.join(samesite)})" if mitigated else
                  " and the session cookie does not set SameSite"), page)
    passed(page, "Every data-changing form carries an anti-forgery token")


# ---------------------------------------------------------------------------
# Load check
# ---------------------------------------------------------------------------

def check_load(page, path: str, users: int, seconds: int, limit_ms: int, max_error_rate: float, **_) -> None:
    import httpx
    goto(page, path)
    cookies = {c["name"]: c["value"] for c in page.context.cookies()}
    target = url(path)
    stop = time.time() + seconds
    lat: list[float] = []
    errors: list[str] = []

    def user_loop(_i):
        with httpx.Client(cookies=cookies, follow_redirects=False, timeout=30) as c:
            while time.time() < stop:
                t0 = time.time()
                try:
                    r = c.get(target)
                    lat.append((time.time() - t0) * 1000)
                    if r.status_code >= 400:
                        errors.append(f"HTTP {r.status_code}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc.__class__.__name__)

    live.shot(page, "executor", "action", f"Started {users} simulated users on {path} for {seconds} s", **_ctx(page))
    with ThreadPoolExecutor(max_workers=users) as pool:
        list(pool.map(user_loop, range(users)))
    total = len(lat) + len([e for e in errors if not e.startswith("HTTP")])
    if not lat:
        defect(f"{path}: no request completed under load ({'; '.join(errors[:3])})", page)
    lat.sort()
    p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))]
    avg = sum(lat) / len(lat)
    rate = len(errors) / max(1, total)
    summary = (f"{users} users for {seconds} s on {path}: {total} requests, {total / seconds:.0f} per second, "
               f"average {avg:.0f} ms, 95th percentile {p95:.0f} ms, {rate:.1%} errors")
    live.emit("executor", "observe", summary, path=path, p95=round(p95), avg=round(avg), requests=total,
              error_rate=round(rate, 4), level="bad" if p95 > limit_ms or rate > max_error_rate else "ok", **_ctx(page))
    problems = []
    if p95 > limit_ms:
        problems.append(f"95th percentile {p95:.0f} ms exceeds the {limit_ms} ms limit")
    if rate > max_error_rate:
        problems.append(f"{rate:.1%} of requests failed (limit {max_error_rate:.0%}): {', '.join(sorted(set(errors))[:3])}")
    if problems:
        defect(f"Under load, {path}: " + "; ".join(problems) + f" ({summary})", page)
    passed(page, summary)


# ---------------------------------------------------------------------------
# Visual snapshots
# ---------------------------------------------------------------------------

VISUAL_DIR = Path(SETTINGS.get("visual_dir") or (Path(__file__).parent.parent / "visual"))
LAYOUT_CSS = """*, *::before, *::after { color: transparent !important; text-shadow: none !important;
  caret-color: transparent !important; animation: none !important; transition: none !important; }
table tbody, table tr:not(:first-child), dl, [aria-live] { display: none !important; }
input::placeholder, textarea::placeholder { color: transparent !important; }"""


def check_visual(page, path: str, key: str, threshold: float, mask: list, full_page: bool = True, **_) -> None:
    from PIL import Image, ImageChops, ImageDraw
    goto(page, path)
    page.wait_for_timeout(300)
    run_dir = Path(os.environ.get("AGENTQA_RUN_DIR", VISUAL_DIR / "adhoc"))
    out = run_dir / "visual"
    out.mkdir(parents=True, exist_ok=True)
    base_dir = VISUAL_DIR / "baselines"
    base_dir.mkdir(parents=True, exist_ok=True)
    view = out / f"{key}-current.png"
    page.screenshot(path=str(view), animations="disabled")
    style = page.add_style_tag(content=LAYOUT_CSS + "".join(f"\n{m} {{ visibility: hidden !important; }}" for m in mask))
    layout = out / f"{key}-layout.png"
    page.screenshot(path=str(layout), animations="disabled")
    style.evaluate("e => e.remove()")
    record = {"key": key, "path": path, "role": getattr(page, "_aq_role", None), "case": getattr(page, "_aq_case", None),
              "current": str(view), "baseline": str(base_dir / f"{key}.png")}
    b_layout, b_view = base_dir / f"{key}-layout.png", base_dir / f"{key}.png"
    if not b_layout.exists():
        b_layout.write_bytes(layout.read_bytes())
        b_view.write_bytes(view.read_bytes())
        record.update(status="baseline", ratio=0.0)
        (out / f"{key}.json").write_text(json.dumps(record), encoding="utf-8")
        live.shot(page, "executor", "observe", f"Saved the first snapshot of {path} as its baseline", **_ctx(page))
        passed(page, f"Baseline snapshot saved for {path}")
        return
    a, b = Image.open(b_layout).convert("RGB"), Image.open(layout).convert("RGB")
    if a.size != b.size:
        canvas = Image.new("RGB", (max(a.width, b.width), max(a.height, b.height)), "white")
        a2, b2 = canvas.copy(), canvas.copy()
        a2.paste(a), b2.paste(b)
        a, b = a2, b2
    diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 24 else 0)
    ratio = diff.histogram()[255] / (diff.width * diff.height)
    record["ratio"] = round(ratio, 5)
    if ratio <= threshold:
        record["status"] = "same"
        (out / f"{key}.json").write_text(json.dumps(record), encoding="utf-8")
        passed(page, f"{path} matches its approved snapshot ({ratio:.2%} of pixels differ)")
        return
    shot = Image.open(view).convert("RGB")
    overlay = shot.copy()
    draw = ImageDraw.Draw(overlay)
    box = diff.getbbox()
    small = diff.resize((max(1, diff.width // 16), max(1, diff.height // 16)))
    for y in range(small.height):
        for x in range(small.width):
            if small.getpixel((x, y)) and x * 16 < shot.width and y * 16 < shot.height:
                draw.rectangle([x * 16, y * 16, x * 16 + 15, y * 16 + 15], fill=(255, 64, 32))
    Image.blend(shot, overlay, 0.35).save(out / f"{key}-diff.png")
    record.update(status="changed", diff=str(out / f"{key}-diff.png"), box=list(box) if box else None)
    (out / f"{key}.json").write_text(json.dumps(record), encoding="utf-8")
    live.shot(page, "executor", "verdict", f"VISUAL CHANGE on {path}: {ratio:.2%} of the layout differs from the "
              "approved snapshot", level="warn", **_ctx(page))
    raise AssertionError(f"VISUAL CHANGE: {path} differs from its approved snapshot ({ratio:.2%} of pixels, "
                         f"threshold {threshold:.2%}); review it on the Visual review page")


# ---------------------------------------------------------------------------
# Manual test cases converted from Excel
# ---------------------------------------------------------------------------

def _invalid_fields(page) -> int:
    try:
        return page.evaluate("() => document.querySelectorAll('input:invalid, select:invalid, textarea:invalid').length")
    except Exception:  # noqa: BLE001
        return 0


FILL_VALID_JS = """f => { const aqW = """ + WIDGET_JS + """;
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const out = [];
  for (const e of f.querySelectorAll('input, select, textarea')) {
    const type = (e.type || '').toLowerCase();
    if (!e.name || ['submit', 'button', 'reset', 'image', 'file', 'password'].includes(type)) continue;
    const hidden = type === 'hidden' || !vis(e);
    const w = hidden ? aqW(e) : null;
    if (hidden && !w) continue;
    if (!(w ? w.required : e.required)) continue;
    const opts = e.tagName === 'SELECT' ? [...e.options].map(o => o.value).filter(Boolean) : (w && w.options ? w.options.map(o => o.value) : []);
    out.push({name: e.name, tag: e.tagName.toLowerCase(), type: w ? (w.kind === 'datepicker' ? 'date' : w.kind) : type,
              label: w ? w.label : '', options: opts});
  }
  return out;
}"""


def contact(role: str, kind: str = "mobile") -> str | None:
    c = (SETTINGS.get("contacts") or {}).get(role) or {}
    return c.get(kind) or (c.get("email") if kind == "mobile" else None) or c.get("mobile")


def _inbox(path: str, **params):
    import urllib.parse
    import urllib.request
    u = SETTINGS.get("inbox_url")
    if not u:
        raise LocatorMissing("no mock inbox is configured (inbox: in project.yaml)")
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v})
    with urllib.request.urlopen(f"{u.rstrip('/')}{path}?{q}", timeout=5) as r:
        return json.loads(r.read())


def wait_message(to: str, since: float, kind: str | None = None, contains: str | None = None,
                 timeout: float | None = None) -> dict | None:
    end = time.time() + float(timeout or SETTINGS.get("inbox_wait_s", 25))
    while time.time() < end:
        try:
            for m in _inbox("/messages", to=to, kind=kind, since=since - 1):
                if not contains or contains.lower() in (m["subject"] + " " + m["body"]).lower():
                    return m
        except OSError as exc:
            raise LocatorMissing(f"the mock inbox at {SETTINGS.get('inbox_url')} is not reachable: {exc}")
        time.sleep(0.5)
    return None


def otp_for(role: str, since: float) -> str:
    to = contact(role, "mobile")
    end = time.time() + float(SETTINGS.get("inbox_wait_s", 25))
    while time.time() < end:
        for m in _inbox("/messages", to=to, since=since - 1):
            if m.get("otp"):
                return m["otp"]
        time.sleep(0.5)
    raise LocatorMissing(f"no OTP reached the mock inbox for {role} ({to})")


# ---------------------------------------------------------------------------
# Functional steps: AgentQA itself (login flow, test data vault, ask-the-tester) is used when the
# run starts from AgentQA (AGENTQA_PROJECT_DIR is set); values are tokens resolved here.
# ---------------------------------------------------------------------------

_AQ: dict = {}
TOKEN = re.compile(r"\{(mobile|username|password|email)(?::(\w+))?\}")


def _aq():
    if "project" not in _AQ:
        try:
            import agentqa.live as aq_live
            aq_live._LIVE = live.get()          # one event stream per worker
            from agentqa import assist, login_flow
            from agentqa.config import Project
            _AQ.update(project=Project(Path(os.environ["AGENTQA_PROJECT_DIR"])), lf=login_flow, assist=assist)
        except Exception as exc:  # noqa: BLE001
            raise LocatorMissing(f"this step needs AgentQA's test data (run it from AgentQA): {exc}")
    return _AQ["project"], _AQ["lf"]


BLOCKED_ROLES: dict[str, str] = {}      # roles whose login failed before this run (set by conftest from blocked.json)


def _account_refused(page, account: str | None, where: str, shown: list[str]) -> None:
    """A login test fails the same way the pre-run login did: the account on the Test data page is the likelier cause,
    so the test is Blocked (with the portal's words), not reported as a defect AgentQA cannot prove."""
    why = BLOCKED_ROLES.get(account or "")
    if why and shown:
        blocked(f"{where}: the portal refused the {account} account ('{shown[0][:120]}'), as it did before this run "
                f"({why[:120]}). Check the account on the Test data page; if it is right, the login itself is broken")


def _visual(page, role: str):
    """The Visual QA agent for this test (one per worker, so its model client is reused)."""
    project, _ = _aq()
    if "visual" not in _AQ:
        from agentqa.agents.visual_qa import VisualQA
        _AQ["visual"] = VisualQA(project, role=role, url_of=url, find_click=find_click, page_text=body)
    _AQ["visual"].role = getattr(page, "_aq_role", role)
    return _AQ["visual"]


def _tokens(account: str | None) -> dict:
    """The test data the Visual QA agent may type, as tokens only: it never sees the values."""
    if not account or account == "anonymous":
        return {}
    project, _ = _aq()
    acc = project.account(account) or {}
    out = {"{" + k + "}": f"the {account}'s {k}" for k in ("mobile", "username", "email") if acc.get(k)}
    if acc.get("password"):
        out["{password}"] = f"the {account}'s password (typed by AgentQA, never shown)"
    return out


def _transform(v: str, how: str | None) -> str:
    if not how:
        return v
    digits = re.sub(r"\D", "", v)
    return {
        "drop_last": v[:-1],
        "extra": v + "1",
        "letters": v[: max(1, len(v) // 2)] + "abcdefghij"[: len(v) - max(1, len(v) // 2)],
        "bad_start": "5" + digits[1:] if digits else "5" + v[1:],
        "last4": digits[-4:] if digits else v[-4:],
        "wrong": v + "#x9",
        "swapcase": v.swapcase() if v.swapcase() != v else v + "x",
        "unknown": "aq.no.such.user",
    }.get(how, v)


def resolve(value, account: str | None):
    """Replace {mobile}, {password:wrong}... with the account's values from the Test data page."""
    if not isinstance(value, str) or "{" not in value or not account:
        return value
    project, lf = _aq()
    acc = project.account(account)

    def one(m):
        kind, how = m.group(1), m.group(2)
        if how == "unknown":
            return "aq.no.such.user"
        v = lf._account_value(project, account, acc, kind)
        if v is None:
            raise LocatorMissing(f"the Test data page has no {kind} for {account}")
        return _transform(str(v), how)
    return TOKEN.sub(one, value)


def _shown(value: str, secret: bool) -> str:
    return "•" * 8 if secret else (f"'{short(value)}'" if value else "nothing")


def _input(page, desc):
    """A box found the way the login flow finds it: by name, then label, then kind."""
    project, lf = _aq()
    snap = lf.scan(page)
    if isinstance(desc, str):
        desc = {"name": desc}
    i = lf._find_input(snap, desc)
    if not i:
        raise LocatorMissing(f"no '{desc.get('label') or desc.get('name') or desc.get('kind')}' box on {_path(page.url)}")
    return page.locator(f'[data-aq-id="{i["id"]}"]').first, i, snap


def _visible(loc):
    try:
        for el in loc.all()[:30]:
            if el.is_visible():
                return el
    except Exception:  # noqa: BLE001
        return None
    return None


def find_click(page, target: str):
    """The visible button, link, menu item or tab called `target`: exact name first, then partial."""
    t = target.strip()
    exact = re.compile(r"^\s*" + re.escape(t) + r"\s*$", re.I)
    part = re.compile(re.escape(t), re.I)
    for rx in (exact, part):
        for r in ("button", "link", "menuitem", "tab"):
            el = _visible(page.get_by_role(r, name=rx))
            if el:
                return el
        el = _visible(page.locator("[onclick], [role=button], summary, label").filter(has_text=rx))
        if el:
            return el
    return _visible(page.get_by_text(part))


def _otp_inputs(page, wait_ms: int = 5000):
    project, lf = _aq()
    end = time.time() + wait_ms / 1000
    while True:
        snap = lf.scan(page)
        if {"otp", "otpbox"} & {i["kind"] for i in snap["inputs"]} or time.time() > end:
            return snap
        page.wait_for_timeout(300)


def _logged_in(page) -> bool:
    project, lf = _aq()
    page.wait_for_timeout(300)
    return lf.logged_in(lf.scan(page), project, True)


def _click_logout(page, where: str):
    project, lf = _aq()
    for _ in range(4):
        snap = lf.scan(page)
        c = next((c for c in snap["clicks"] if lf.LOGOUT.search(c["text"])), None)
        if c:
            loc = page.locator(f'[data-aq-id="{c["id"]}"]').first
            live.shot(page, "executor", "action", f"Clicked '{c['text']}'", loc, **_ctx(page))
            loc.click()
            page.wait_for_load_state("load")
            page.wait_for_timeout(300)
            return
        # Logout is often inside a profile or user menu: open one and look again
        menu = next((c for c in snap["clicks"] if re.search(r"profile|account|\buser\b|welcome|my account|▾|☰|menu",
                                                             c["text"], re.I) and not c.get("href")), None)
        if not menu:
            break
        page.locator(f'[data-aq-id="{menu["id"]}"]').first.click()
        page.wait_for_timeout(400)
    raise LocatorMissing(f"{where}: no Logout button or link on {_path(page.url)}")


REF_RE = re.compile(r"(?:application|reference|ref|request|ticket|tracking|acknowledg\w*|registration|token)\s*(?:no\.?|number|id|#)"
                    r"\s*(?:is\s*)?[:#]?\s*([A-Z0-9][A-Z0-9/-]{2,})", re.I)


def _rows_with(page, ref: str):
    return [r for r in page.locator("tr, li, [role=row], .card").all()[:400] if ref in (r.inner_text() or "")]


def run_steps(open_role, role: str, steps: list[dict]) -> None:
    page = open_role(role)
    before = ""
    st_started_all = time.time()
    last_click = {"at": time.time(), "target": ""}
    V: dict[str, str] = {}          # values carried between steps and roles (an application number...)

    def sub(x):
        if isinstance(x, str) and "{" in x:
            for k, v in V.items():
                x = x.replace("{" + k + "}", v)
        return x

    pause_flag = Path(os.environ.get("AGENTQA_PROJECT_DIR") or ".") / ".agentqa" / "pause.flag"
    for i, st in enumerate(steps, 1):
        st = {k: sub(v) for k, v in st.items()}
        if pause_flag.exists():
            # Pause and take over: this browser is handed to the person; the test goes on from where they leave it
            project, _ = _aq()
            res = _AQ["assist"].checkpoint(project, page, role=getattr(page, "_aq_role", role), agent="executor",
                                           where=f"step {i} of {getattr(page, '_aq_case', 'this test')}")
            if res:
                step_log("action", f"A person had the browser before step {i} ({len(res.get('events') or [])} action(s))", page)
        st_started = time.time()
        a = st.get("action")
        acct = st.get("account")
        if st.get("role") and st["role"] != getattr(page, "_aq_role", role):
            page = open_role(st["role"])          # the next user in the workflow, in their own browser session
            before = ""
            step_log("action", f"Switched to {st['role']}", page)
        where = f"step {i} ('{st.get('text', '')[:60]}')"
        fail = st.get("fail")
        if a in ("session", "skip"):
            live.emit("executor", "step", f"{where}: {st.get('why') or 'using the saved ' + str(st.get('role')) + ' session'}",
                      **_ctx(page))
            continue
        if a == "manual":
            live.emit("executor", "step", f"{where}: left for a person to check ({st.get('why')})", level="warn",
                      **_ctx(page))
            continue
        if a == "note":
            live.emit("executor", "step", st.get("text") or "", **_ctx(page))
            continue
        if a == "goto":
            status, _ = goto(page, st["path"])
            V["__last_status"] = str(status)
            before = body(page)
            if status >= 500:
                defect(f"{where}: {st['path']} returned HTTP {status}", page)
        elif a == "fill":
            value = resolve(st.get("value"), acct)
            if isinstance(st.get("field"), dict) or acct:
                loc, _, _ = _input(page, st["field"])
                loc.fill("" if value is None else str(value))
                live.shot(page, "executor", "action", f"Typed {_shown(str(value or ''), bool(st.get('secret')))}", loc, **_ctx(page))
            else:
                set_value(page, st["field"], value)
            step_log("action", st.get("text") or f"Filled {st.get('field')}", page)
        elif a == "fill_valid":
            form = page.locator("form").filter(has=page.locator("input:not([type=hidden]), select, textarea")).first
            for f in form.evaluate(FILL_VALID_JS):
                value = {"email": "qa.tester@example.com", "tel": "9876543210", "date": "1990-05-15", "number": "10",
                         "checkbox": "on", "richtext": "Test purpose text"}.get(f["type"])
                if f["options"]:
                    value = f["options"][0]
                if value is None:
                    n = (f["name"] + " " + f["label"]).lower()
                    value = ("9876543210" if "mobile" in n or "phone" in n else "695001" if "pin" in n
                             else "1990-05-15" if "date" in n or "dob" in n
                             else "1 Test Road" if "address" in n else "Test User")
                set_value(page, f["name"], value)
        elif a == "upload":
            set_value(page, st["field"], st.get("value") or "@file:document.pdf")
        elif a == "fill_otp" and acct:
            project, lf = _aq()
            snap = _otp_inputs(page)
            if not {"otp", "otpbox"} & {x["kind"] for x in snap["inputs"]}:
                _account_refused(page, acct, where, snap["alerts"])
                defect(f"{where}: the OTP screen did not appear on {_path(page.url)}"
                       + (f" ({'; '.join(snap['alerts'][:2])})" if snap["alerts"] else ""), page)
            n = sum(1 for x in snap["inputs"] if x["kind"] == "otpbox") or 6
            if st.get("value") == "wrong":
                fixed = str(project.account(acct).get("otp_fixed") or "")
                code = (fixed[:-1] + str((int(fixed[-1]) + 1) % 10)) if fixed[-1:].isdigit() else "0" * n
            elif st.get("value") == "blank":
                code = ""
            else:
                code = lf.otp_for(project, acct, page, last_click["at"], "executor")
            lf._fill_otp(page, lf.scan(page), code)
            live.shot(page, "executor", "action", "Typed " + ("a wrong OTP" if st.get("value") == "wrong" else "the OTP (hidden)"),
                      **_ctx(page))
        elif a == "fill_otp":
            code = otp_for(role, since=st_started)
            set_value(page, st["field"], code)
        elif a == "captcha":
            project, lf = _aq()
            ans = _AQ["assist"].ask(project, "captcha", "Type the CAPTCHA shown on the screen", agent="executor", page=page)
            if not ans or not ans.get("text"):
                raise LocatorMissing(f"{where}: nobody typed the CAPTCHA")
            loc, _, _ = _input(page, st.get("field") or {"kind": "captcha"})
            loc.fill(ans["text"])
        elif a == "login_as":
            project, lf = _aq()
            steps_ = project.vault.login_steps(acct)
            try:
                if steps_:
                    lf.replay(page, project, acct, steps_, agent="executor")
                else:
                    lf.login(page, project, acct, agent="executor")
            except lf.LoginError as exc:
                blocked(f"{where}: could not log in as {acct}, so this test cannot run ({exc})")
            before = body(page)
            step_log("action", f"Logged in as {acct}", page)
        elif a == "wait":
            secs = float(st.get("seconds") or 0)
            hook = SETTINGS.get("clock_hook") or {}
            if hook.get("url"):
                r = page.request.post(url(hook["url"]), headers=hook.get("headers") or {},
                                      data=json.dumps({"advance_s": secs + 5}), fail_on_status_code=False)
                if r.status >= 400:
                    blocked(f"{where}: the test clock at {hook['url']} answered HTTP {r.status}")
                step_log("action", f"Moved the portal's test clock forward {int(secs + 5)} s ({st.get('why', 'waiting')})", page)
            elif secs <= float(SETTINGS.get("max_wait_s") or 90):
                step_log("action", f"Waiting {int(secs)} s ({st.get('why', '')})", page)
                page.wait_for_timeout((secs + 3) * 1000)
            else:
                not_run(f"{where}: needs {int(secs)} s of waiting ({st.get('why', '')}); set functional.max_wait_s to at least "
                        f"{int(secs) + 5} or give the test environment a clock hook (functional.clock_hook)")
        elif a in ("expect_email", "expect_sms"):
            kind = "email" if a == "expect_email" else "sms"
            to = st.get("to") or contact(role, "email" if kind == "email" else "mobile")
            m = wait_message(to, since=st_started_all, kind=kind, contains=st.get("contains"))
            if not m:
                defect(f"{where}: no {kind} reached {to} within {SETTINGS.get('inbox_wait_s', 25)} s "
                       f"(checked the mock inbox at {SETTINGS.get('inbox_url')})", page)
            live.emit("executor", "observe", f"{where}: {kind} to {to}: '{m['subject'] or m['body'][:60]}'", **_ctx(page))
            passed(page, f"{where}: {kind} received: {m['subject'] or m['body'][:60]}")
        elif a == "expect_new_message":
            project, lf = _aq()
            src = lf.otp_source(project, acct)
            number = re.sub(r"\D", "", str(project.account(acct).get("mobile") or ""))
            if src == "inbox" and SETTINGS.get("inbox_url"):
                # the first OTP of this test plus a new one: count them, so a late first SMS is not taken for the new one
                end = time.time() + float(SETTINGS.get("inbox_wait_s", 25))
                msgs = []
                while time.time() < end:
                    msgs = _inbox("/messages", to=number[-10:], kind="sms", since=st_started_all)
                    if len(msgs) >= 2:
                        break
                    time.sleep(0.5)
                if len(msgs) < 2:
                    defect(f"{where}: no new OTP SMS reached ******{number[-4:]} within {SETTINGS.get('inbox_wait_s', 25)} s "
                           f"after clicking '{last_click['target']}' ({len(msgs)} SMS in this test)", page)
                passed(page, f"{where}: a new SMS arrived ({len(msgs)} in this test)")
            else:
                ans = _AQ["assist"].ask(project, "confirm", f"Did a new OTP arrive on ******{number[-4:]}? AgentQA just clicked "
                                        f"'{last_click['target']}'.", role=acct, agent="executor", page=page,
                                        options=["Yes, a new OTP arrived", "No, nothing new arrived"])
                if not ans:
                    raise LocatorMissing(f"{where}: nobody confirmed whether a new OTP arrived")
                if ans.get("option") == 1 or ans.get("ok") is False:
                    defect(f"{where}: no new OTP arrived after clicking '{last_click['target']}' (confirmed by the tester)", page)
                passed(page, f"{where}: the tester confirmed a new OTP arrived")
        elif a == "click_el":
            d = st.get("el") or {}

            def q(v):
                return '"' + str(v).replace('\\', '\\\\').replace('"', '\\"') + '"'
            sels = ([f"[id={q(d['elid'])}]"] if d.get("elid") else []) + ([f"[aria-label={q(d['aria'])}]"] if d.get("aria") else []) \
                + ([f"[title={q(d['title'])}]"] if d.get("title") else []) + ([f"[name={q(d['name'])}]"] if d.get("name") else []) \
                + ([f"a[href={q(d['href'])}]"] if d.get("href") else [])
            loc = next((page.locator(x).first for x in sels if page.locator(x).count()), None)
            if loc is not None:
                loc.click()
            elif (st.get("at") or {}).get("x") is not None:
                page.mouse.click(float(st["at"]["x"]), float(st["at"]["y"]))
            else:
                raise LocatorMissing(f"{where}: the control a tester showed is no longer on {_path(page.url)}")
            page.wait_for_load_state("load")
            step_log("action", st.get("text") or "Clicked the control a tester showed", page)
        elif a == "click":
            target = st["target"]
            loc = find_click(page, target)
            if loc is None:
                raise LocatorMissing(f"{where}: nothing called '{target}' on {_path(page.url)}")
            before = body(page)
            ev = live.shot(page, "executor", "action", f"Clicked '{target}'", loc, **_ctx(page))
            step_log("before", f"About to click '{target}'", page, ev)
            try:
                loc.evaluate("e => { const f = e.closest('form'); if (f) f.noValidate = false; }")
            except Exception:  # noqa: BLE001
                pass
            last_click.update(at=time.time(), target=target)
            loc.click()
            page.wait_for_load_state("load")
            page.wait_for_timeout(250)
            ev = live.shot(page, "executor", "observe", f"{where}: now on {_path(page.url)}", **_ctx(page))
            step_log("after", f"Clicked '{target}'; now on {_path(page.url)}", page, ev)
        elif a == "click_logout":
            before = body(page)
            last_click.update(at=time.time(), target="Logout")
            _click_logout(page, where)
        elif a == "click_at":
            page.mouse.click(st["x"], st["y"])
            page.wait_for_load_state("load")
        elif a == "press":
            before = body(page)
            last_click.update(at=time.time(), target=st["key"])
            page.keyboard.press(st["key"])
            page.wait_for_load_state("load")
            page.wait_for_timeout(250)
        elif a == "back":
            page.go_back(wait_until="load")
            live.shot(page, "executor", "navigate", f"Back to {_path(page.url)}", **_ctx(page))
        elif a == "reload":
            page.reload(wait_until="load")
            live.shot(page, "executor", "navigate", f"Reloaded {_path(page.url)}", **_ctx(page))
        elif a == "expect_text":
            want = str(resolve(st.get("value") or st["text"], acct))
            if want.lower() not in body(page):
                defect(f"{where}: " + (fail or f"expected '{want if not acct else 'the account value'}' on screen") +
                       f"; page says: {'; '.join(alerts(page)) or body(page)[:160]}", page)
            passed(page, f"{where}: seen")
        elif a == "expect_no_text":
            want = str(resolve(st.get("value"), acct))
            if want and want.lower() in body(page):
                defect(f"{where}: " + (fail or "the screen shows what it must not show"), page)
            passed(page, f"{where}: not shown")
        elif a == "expect_any_text":
            text = body(page)
            if not any((re.search(v, text, re.I) if st.get("regex") else v.lower() in text) for v in st.get("values") or []):
                defect(f"{where}: " + (fail or "none of the expected messages appeared") + f"; page says: {text[:160]}", page)
            passed(page, f"{where}: message shown")
        elif a == "expect_text_literal":
            want = str(st.get("value"))
            if want.lower() not in body(page):
                bare = re.sub(r"<[^>]+>", "", want).lower()
                how = "the typed HTML was turned into page content (not escaped)" if bare and bare in body(page) else \
                    "the typed text is not shown"
                defect(f"{where}: {fail or how}: '{want}'", page)
            passed(page, f"{where}: shown as typed")
        elif a == "expect_no_server_error":
            text = body(page)
            if any(p in text for p in ORACLES["server_error_patterns"]) or "internal server error" in (page.title() or "").lower():
                defect(f"{where}: a server error page appeared at {_path(page.url)}", page)
            passed(page, f"{where}: no server error")
        elif a == "expect_success":
            after = body(page)
            if not any(after.count(p) > before.count(p) for p in ORACLES["success_patterns"]):
                defect(f"{where}: no success message; page says: {'; '.join(alerts(page)) or after[:160]}", page)
            passed(page, f"{where}: success message shown")
        elif a == "expect_error":
            after = body(page)
            shown = alerts(page) or [p for p in ORACLES["error_patterns"] if after.count(p) > before.count(p)]
            if not shown and not _invalid_fields(page):
                defect(f"{where}: " + (fail or "no error or validation message appeared"), page)
            passed(page, f"{where}: error shown ({'; '.join(shown[:2]) or 'browser validation'})")
        elif a == "expect_field":
            snap = _otp_inputs(page) if st.get("kind") == "otp" else _aq()[1].scan(page)
            kinds = {x["kind"] for x in snap["inputs"]}
            want = {"otp", "otpbox"} if st.get("kind") == "otp" else {st.get("kind")}
            if not (want & kinds):
                defect(f"{where}: " + (fail or f"the {st.get('kind')} box did not appear") + f" on {_path(page.url)}"
                       + (f" ({'; '.join(snap['alerts'][:2])})" if snap["alerts"] else ""), page)
            passed(page, f"{where}: the {st.get('kind')} box is shown")
        elif a == "expect_no_field":
            page.wait_for_timeout(300)
            snap = _aq()[1].scan(page)
            kinds = {x["kind"] for x in snap["inputs"]}
            want = {"otp", "otpbox"} if st.get("kind") == "otp" else {st.get("kind")}
            if want & kinds:
                defect(f"{where}: {fail or 'a box appeared that must not'} (now on {_path(page.url)}"
                       + (f", the screen says: {snap['alerts'][0]}" if snap["alerts"] else "")
                       + (f", '{body(page)[:80]}'" if not snap["alerts"] else "") + ")", page)
            passed(page, f"{where}: not shown")
        elif a == "expect_logged_in":
            if not _logged_in(page):
                _account_refused(page, acct or getattr(page, "_aq_role", role), where, alerts(page))
                defect(f"{where}: not logged in; now on {_path(page.url)}; the screen says: "
                       f"{'; '.join(alerts(page)) or body(page)[:140]}", page)
            passed(page, f"{where}: logged in, now on {_path(page.url)}")
        elif a == "expect_session":
            names = [c["name"] for c in page.context.cookies(page.url)]
            stored = page.evaluate("() => [...Object.keys(localStorage), ...Object.keys(sessionStorage)]"
                                   ".filter(k => /token|auth|session|jwt|user/i.test(k))")
            if not names and not stored:
                defect(f"{where}: no session cookie or token was stored after logging in", page)
            passed(page, f"{where}: session kept in " + ", ".join(names[:3] + stored[:2]))
        elif a == "expect_logged_out":
            page.wait_for_timeout(250)
            snap = _aq()[1].scan(page)
            if snap["logout"]:
                defect(f"{where}: " + (fail or "still logged in (Logout is still offered)") + f" at {_path(page.url)}", page)
            passed(page, f"{where}: not logged in")
        elif a == "expect_max_length":
            loc, _, _ = _input(page, st["field"])
            value = str(resolve(st.get("value"), acct))
            loc.fill(value)
            got = loc.input_value()
            live.shot(page, "executor", "observe", f"Typed {len(value)} characters; the box holds {len(got)}", loc, **_ctx(page))
            if len(got) > int(st["max"]):
                defect(f"{where}: the box accepted {len(got)} characters (limit {st['max']})", page)
            passed(page, f"{where}: the box holds {len(got)} of {len(value)} typed characters")
        elif a == "expect_masked":
            loc, info, _ = _input(page, st["field"])
            if (loc.get_attribute("type") or "").lower() != "password":
                defect(f"{where}: the {info.get('label') or 'password'} box shows what is typed (type="
                       f"{loc.get_attribute('type')})", page)
            passed(page, f"{where}: the password box is masked")
        elif a == "expect_denied":
            text = body(page)
            final = _path(page.url)
            st_status = V.get("__last_status")
            nf = _not_found(int(st_status) if str(st_status).isdigit() else 0, text)
            if not (is_login(final) or any(p in text for p in ORACLES["denied_patterns"]) or nf):
                defect(f"{where}: expected access to be denied, but {final} opened normally", page)
            passed(page, f"{where}: access denied as expected" + (" (page not reachable)" if nf else ""))
        elif a == "expect_path":
            now_path = _path(page.url)
            ok = (now_path.split("?")[0].rstrip("/") or "/") == (st["path"].rstrip("/") or "/") if st.get("exact") \
                else now_path.startswith(st["path"])
            if not ok:
                defect(f"{where}: expected to be on {st['path']}, but on {now_path}", page)
            passed(page, f"{where}: on {st['path']}")
        elif a == "expect_visible":
            want = str(resolve(st.get("value"), acct))
            if not _visible(page.get_by_text(want, exact=False)) and find_click(page, want) is None:
                defect(f"{where}: '{want}' is not shown on {_path(page.url)}", page)
            passed(page, f"{where}: '{want}' is shown")
        elif a == "expect_page":
            want = str(st.get("value") or st["text"])
            words = [w for w in re.findall(r"[a-z]{3,}", want.lower()) if w not in ("the", "and", "page")]
            title = (page.title() or "").lower() + " " + body(page)[:300]
            status_bad = any(x in title for x in ("not found", "error", "access denied"))
            if status_bad or (words and not any(w in title for w in words)):
                defect(f"{where}: expected the {want} page; got '{page.title()}' at {_path(page.url)}", page)
            passed(page, f"{where}: {want} page shown")
        elif a == "capture_ref":
            text = " ".join(alerts(page)) + " " + page.inner_text("body")
            m = REF_RE.search(text)
            if not m:
                defect(f"{where}: no application or reference number was shown after submitting; page says: "
                       f"{'; '.join(alerts(page)) or body(page)[:160]}", page)
            V[st.get("as") or "ref"] = m.group(1)
            live.emit("executor", "observe", f"{where}: noted the number {m.group(1)} for the next users", **_ctx(page))
            passed(page, f"{where}: reference {m.group(1)} shown")
        elif a == "click_record":
            ref, stem = str(st["ref"]), str(st["verb"]).lower()[:5]
            cands = [el for el in page.locator("button, a, input[type=submit], [role=button]").all()[:300] if el.is_visible()]

            def label(el):
                return (el.inner_text() or el.get_attribute("value") or el.get_attribute("aria-label") or "").strip()
            hits = [el for el in cands if stem in label(el).lower() and (ref in label(el) or ref in (el.evaluate(
                "e => (e.closest('tr, li, [role=row], .card') || e).innerText") or ""))]
            if not hits:
                defect(f"{where}: {ref} is not on {_path(page.url)} with a '{st['verb']}' action, so it did not reach "
                       f"{getattr(page, '_aq_role', 'this role')}", page)
            before = body(page)
            ev = live.shot(page, "executor", "action", f"Clicked '{label(hits[0])}'", hits[0], **_ctx(page))
            step_log("before", f"About to click '{label(hits[0])}'", page, ev)
            last_click.update(at=time.time(), target=label(hits[0]))
            hits[0].click()
            page.wait_for_load_state("load")
            page.wait_for_timeout(250)
            ev = live.shot(page, "executor", "observe", f"{where}: now on {_path(page.url)}", **_ctx(page))
            step_log("after", f"Clicked '{last_click['target']}'", page, ev)
        elif a == "expect_record_status":
            ref, want = str(st["ref"]), str(st["status"])
            rows = _rows_with(page, ref)
            if not rows:
                defect(f"{where}: {ref} is not listed on {_path(page.url)}", page)
            row_text = re.sub(r"\s+", " ", rows[0].inner_text()).strip()
            live.shot(page, "executor", "observe", f"{where}: {ref} reads '{row_text[:80]}'", rows[0], **_ctx(page))
            if want.lower() not in row_text.lower():
                defect(f"{where}: {ref} shows '{row_text[:100]}', expected the status '{want}'", page)
            passed(page, f"{where}: {ref} is '{want}'")
        elif a == "expect_record_listed":
            ref = str(st["ref"])
            if not _rows_with(page, ref) and ref not in page.inner_text("body"):
                defect(f"{where}: {ref} is not on {_path(page.url)}: it did not reach {getattr(page, '_aq_role', 'this role')}",
                       page)
            passed(page, f"{where}: {ref} is listed")
        elif a == "intent":
            # a step written as what a tester does, not how: the Visual QA agent works it out from the screen
            vq = _visual(page, role)
            app = split_path(_path(page.url) if page.url.startswith("http") else "/")[0]
            prod = bool((APPS.get(app) or {}).get("production"))
            res = vq.act(page, st["text"], tokens=_tokens(acct or getattr(page, "_aq_role", role)),
                         resolve=lambda v: resolve(v, acct or getattr(page, "_aq_role", role)), production=prod)
            for t in vq.trace:
                step_log("visual-qa", t["text"], page)
            vq.trace.clear()
            if not res["ok"]:
                if not res.get("asked") and vq.llm is None:
                    not_run(f"{where}: needs an AI model (AI providers page) or a person (visual_qa.ask_person) to "
                            f"carry out '{st['text']}'")
                blocked(f"{where}: the Visual QA agent could not '{st['text']}': {res['why']}")
            live.shot(page, "executor", "action", f"Visual QA ({res['by']}): {st['text']} - "
                      + ("; ".join(res["actions"]) or "already done"), **_ctx(page))
            step_log("action", f"{st['text']} ({res['by']}: {'; '.join(res['actions']) or 'no action needed'})", page)
        elif a == "verify":
            vq = _visual(page, role)
            res = vq.verify(page, st["expect"])
            for t in vq.trace:
                step_log("visual-qa", t["text"], page)
            vq.trace.clear()
            if res["verdict"] == "fail":
                defect(f"{where}: expected '{st['expect']}', but {res['why'] or 'the page does not show it'}"
                       + (f" (page shows: '{res['quote'][:120]}')" if res["quote"] else ""), page)
            if res["verdict"] != "pass":
                if res["by"] is None and vq.llm is None:
                    not_run(f"{where}: needs an AI model or a person to judge '{st['expect']}'")
                raise LocatorMissing(f"{where}: NOT VERIFIED: could not confirm '{st['expect']}': {res['why']}")
            passed(page, f"{where}: {st['expect']}" + (f" - the page shows '{res['quote'][:120]}'" if res["quote"] else
                                                      f" ({res['why']})"))
        else:
            raise LocatorMissing(f"{where}: unknown step '{a}'")
