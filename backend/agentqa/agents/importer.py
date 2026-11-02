"""Test-case Importer: turns a team's manual test cases (Excel or CSV) into automated tests.

Reads the usual manual-test layouts: one row per case with numbered steps in one
cell, or one row per step under a case ID. Each step is matched against what the
Explorer saw (screens, link texts, field labels, option lists) with a keyword
grammar: open/navigate, enter/type, select, tick, click, verify. Steps it cannot
read stay as manual checkpoints and the case is marked for review, so nothing is
guessed silently. Approved cases become tests of type "manual_converted".

No AI model is needed. When the optional local model is on, it is asked only to
rewrite steps the grammar could not read into the same simple form.
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from agentqa import live
from agentqa.agents.reconciler import app_index
from agentqa.config import Project
from agentqa.store import Store, now
from agentqa.util import similarity, valid_value

HEADERS = {
    "id": ["test case id", "tc id", "tc no", "test id", "case id", "id", "s no", "sl no", "test case no"],
    "title": ["test scenario", "scenario", "test case name", "title", "test case title", "summary", "test case",
              "description", "test case description", "objective"],
    "pre": ["pre-condition", "precondition", "pre condition", "pre-requisite", "prerequisite", "preconditions"],
    "steps": ["test steps", "steps", "steps to execute", "procedure", "test procedure", "action", "actions"],
    "data": ["test data", "data", "input data", "inputs"],
    "expected": ["expected result", "expected results", "expected", "expected outcome", "expected behaviour",
                 "expected behavior"],
    "role": ["role", "user", "user role", "actor", "login as", "persona"],
    "req": ["requirement id", "req id", "requirement", "srs ref", "reference", "fr id"],
}
ANON = re.compile(r"\b(anonymous|public|guest|visitor|not logged in|without login|logged out)\b", re.I)
QUOTED = re.compile(r"[\"'‘’“”]([^\"'‘’“”]{1,120})[\"'‘’“”]")


# ---------------------------------------------------------------------------
# reading the file
# ---------------------------------------------------------------------------

def _rows(path: Path) -> list[list[str]]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        out = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                out.append(["" if v is None else str(v).strip() for v in row])
            if out:
                break
        return out
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text))]


def _header(rows: list[list[str]]) -> tuple[int, dict]:
    best, best_map = -1, {}
    for i, row in enumerate(rows[:15]):
        cols = {}
        for j, cell in enumerate(row):
            c = re.sub(r"[^a-z ]", " ", cell.lower()).strip()
            c = re.sub(r"\s+", " ", c)
            for key, names in HEADERS.items():
                if key not in cols and (c in names or any(c.startswith(n) for n in names if len(n) > 4)):
                    cols[key] = j
                    break
        if "steps" in cols and len(cols) > len(best_map):
            best, best_map = i, cols
    return best, best_map


def read_cases(path: Path) -> list[dict]:
    rows = _rows(path)
    hi, cols = _header(rows)
    if hi < 0:
        raise ValueError("No header row with a Steps column was found. Expected columns such as "
                         "'Test Case ID', 'Test Scenario', 'Test Steps', 'Expected Result'.")
    get = lambda r, k: (r[cols[k]] if k in cols and cols[k] < len(r) else "").strip()  # noqa: E731
    cases: list[dict] = []
    for r in rows[hi + 1:]:
        if not any(r):
            continue
        cid, steps = get(r, "id"), get(r, "steps")
        if not cid and cases and (steps or get(r, "expected")):
            c = cases[-1]  # a continuation row: one step per row
        else:
            if not steps and not get(r, "title"):
                continue
            c = {"id": cid or f"MT-{len(cases) + 1:03d}", "title": get(r, "title"), "pre": get(r, "pre"),
                 "steps": [], "data": get(r, "data"), "expected": [], "role": get(r, "role"), "req": get(r, "req")}
            cases.append(c)
        c["steps"] += _split(steps)
        c["expected"] += _split(get(r, "expected"))
        if get(r, "data") and get(r, "data") not in c["data"]:
            c["data"] = (c["data"] + "\n" + get(r, "data")).strip()
    return cases


def _split(text: str) -> list[str]:
    parts = re.split(r"\n+|(?<=[.;])\s+(?=\d+[.)]\s)|;\s*(?=[A-Z])", text or "")
    out = []
    for p in parts:
        p = re.sub(r"^\s*(step\s*)?\d+\s*[.):-]\s*", "", p.strip(), flags=re.I).strip(" .;")
        if p:
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# converting steps
# ---------------------------------------------------------------------------

class Context:
    def __init__(self, project: Project, store: Store):
        self.project = project
        self.by_path, self.fields = app_index(project, store)
        self.roles = project.role_aliases()
        self.screens = store.all("SELECT path, role, links, forms, buttons, title FROM screens")
        self.links: dict[str, str] = {}
        for s in self.screens:
            for link in s["links"] or []:
                if link["text"] and project.is_internal(link["href"]):
                    self.links.setdefault(link["text"].strip().lower(), project.rel(link["href"]) or "/")

    def role_of(self, text: str) -> str | None:
        if ANON.search(text or ""):
            return "anonymous"
        low = (text or "").lower()
        best = None
        for role, names in self.roles.items():
            for n in names:
                if re.search(rf"\b{re.escape(n)}s?\b", low):
                    if not best or len(n) > best[1]:
                        best = (role, len(n))
        return best[0] if best else None

    def screen(self, target: str, role: str | None = None) -> str | None:
        t = target.strip().strip("'\"").lower()
        t = re.sub(r"^(the|a|an)\s+", "", t)
        t = re.sub(r"\s+(page|screen|menu|link|tab|module|section|url|option)$", "", t).strip()
        if t.startswith("/"):
            return self._qualify(t.split()[0], role)
        if t.startswith("@"):
            return t.split()[0]
        if t.startswith("http"):
            return self.project.rel(t.split()[0]) or "/"
        if t in ("home", "home page", "homepage", "landing"):
            return "/"
        best, score = None, 0.0
        for text, path in self.links.items():
            s = similarity(t, text)
            if s > score:
                best, score = path, s
        for path, e in self.by_path.items():
            s = max(similarity(t, e["name"]), similarity(t, (e["title"] or "")), *(similarity(t, x) for x in e["links_to"]))
            if s > score:
                best, score = path, s
        return best if score >= 0.6 else None

    def _qualify(self, path: str, role: str | None) -> str:
        """An unqualified '/officer/queue' from a manual test belongs to the role's own portal when the primary
        portal has no such screen but another application does. Keeps multi-portal manual tests pointing at the
        right site instead of 404-ing on the primary one."""
        prim = self.project.primary_app
        if path.startswith("@") or self.project.split_path(path)[0] != prim:
            return path
        if any(s["path"] == path for s in self.screens):
            return path                              # the primary portal really has this page
        app = self.project.app_of(role) if role else prim
        cand = self.project.qualify(path, app)
        if app != prim and any(s["path"] == cand for s in self.screens):
            return cand
        # otherwise, any single other application that has it (an unambiguous match)
        matches = {self.project.split_path(s["path"])[0] for s in self.screens
                   if s["path"].startswith("@") and self.project.split_path(s["path"])[1] == path}
        return self.project.qualify(path, next(iter(matches))) if len(matches) == 1 else path

    def field(self, label: str, path: str | None) -> dict | None:
        label = re.sub(r"\s+(field|textbox|text box|box|input|dropdown|drop down|combo ?box|checkbox|check box)$", "",
                       label.strip().strip("'\""), flags=re.I)
        best, score = None, 0.0
        for f in self.fields:
            if path and f["path"] != path:
                continue
            fld = f["field"]
            s = max(similarity(label, fld.get("label")), similarity(label, fld.get("name")),
                    similarity(label, fld.get("placeholder")))
            if s > score:
                best, score = f, s
        return best if score >= 0.6 else None


def _value(raw: str, data: dict, field: dict | None) -> str | None:
    raw = raw.strip()
    q = QUOTED.search(raw)
    if q:
        return q.group(1)
    key = raw.lower().strip(" .")
    if key in data:
        return data[key]
    if re.fullmatch(r"(a |any )?valid( value| data| input)?", key) and field:
        return valid_value(field["field"])
    if re.search(r"\binvalid\b", key):
        return None
    return raw.strip(" .")


def _data(text: str) -> dict:
    out = {}
    for part in re.split(r"[\n;,]+", text or ""):
        m = re.match(r"\s*([^:=]{1,40})\s*[:=]\s*(.+)", part)
        if m:
            out[m.group(1).strip().lower()] = m.group(2).strip().strip("'\"")
    return out


def convert_step(text: str, ctx: Context, state: dict, data: dict) -> dict:
    t = text.strip()
    low = t.lower()
    step = {"text": t}
    path = state.get("path")
    # login / role
    m = re.match(r"(?:log ?in|sign ?in|login)\s+(?:to the (?:portal|application|system)\s+)?(?:as|with)\s+(.+)", low)
    if m or re.match(r"(user|.+) is logged in", low):
        role = ctx.role_of(t)
        if role:
            state["role"] = role
            return {**step, "action": "session", "role": role, "ok": True}
        return {**step, "action": "manual", "ok": False, "why": "unknown role"}
    if re.match(r"(log ?out|sign ?out)\b", low):
        return {**step, "action": "skip", "ok": True, "why": "logout is skipped so the shared test session stays valid"}
    # upload a file
    m = re.match(r"(?:upload|attach|browse and (?:select|upload)|choose)\s+(?:a |an |the )?(.+?)(?:\s+(?:as|in|into|for|to|under|using)\s+(?:the\s+)?(.+?))?(?:\s+field)?$", low)
    if m and re.match(r"(upload|attach|browse)", low):
        files_here = [x for x in ctx.fields if x["path"] == path and (x["field"].get("type") or "") == "file"]
        f = ctx.field(m.group(2), path) if m.group(2) else None
        if not (f and f["field"].get("type") == "file"):
            f = files_here[0] if len(files_here) == 1 else None
        if not path:
            return {**step, "action": "manual", "ok": False, "why": "no screen is open yet"}
        if not f:
            return {**step, "action": "manual", "ok": False, "why": "no file field on the current screen matches"}
        ext = re.search(r"\b(pdf|jpe?g|png|docx?|xlsx?|csv|txt|gif|zip)\b", m.group(1))
        accept = [x.strip().lstrip(".") for x in (f["field"].get("accept") or "").split(",") if x.strip() and "/" not in x]
        ext = (ext.group(1) if ext else (accept[0] if accept else "pdf")).replace("jpeg", "jpg")
        return {**step, "action": "upload", "field": f["field"]["name"], "label": f["field"].get("label"),
                "value": f"@file:{re.sub(r'[^a-z0-9]+', '_', m.group(1))[:30].strip('_') or 'document'}.{ext}", "ok": True}
    # one-time password from the mock inbox
    if re.search(r"\b(otp|one[- ]time password|verification code)\b", low) and re.match(r"(enter|type|input|key in|fill)", low):
        f = ctx.field("otp", path) or ctx.field("one time password", path)
        if not f:
            return {**step, "action": "manual", "ok": False, "why": "no OTP field on the current screen"}
        if not (ctx.project.account(state.get("role") or "") or {}).get("mobile") and not (
                ctx.project.account(state.get("role") or "") or {}).get("email"):
            return {**step, "action": "manual", "ok": False, "why": "add this role's mobile or email to project.yaml"}
        return {**step, "action": "fill_otp", "field": f["field"]["name"], "label": f["field"].get("label"), "ok": True}
    if re.search(r"\bdownload\b|\bcaptcha\b", low):
        return {**step, "action": "manual", "ok": False, "why": "downloads and CAPTCHA are not automated (CAPTCHA must be "
                                                                 "switched off in test environments)"}
    # fill all fields with valid data
    if re.search(r"(enter|fill|provide)\s+(all\s+)?(the\s+)?(valid|correct|proper)\s+(details|data|values|information)", low) \
            or re.search(r"fill (in )?(all )?(the )?(mandatory|required) fields", low):
        if not path:
            return {**step, "action": "manual", "ok": False, "why": "no screen is open yet"}
        return {**step, "action": "fill_valid", "path": path, "ok": True}
    # open / navigate
    m = re.match(r"(?:open|navigate to|go to|visit|launch|access|browse to|click on menu|select menu)\s+(?:the\s+)?(?:url\s+)?(.+)", low)
    if m:
        p = ctx.screen(m.group(1), state.get("role"))
        if p:
            state["path"] = p
            return {**step, "action": "goto", "path": p, "ok": True}
        return {**step, "action": "manual", "ok": False, "why": f"no screen matches '{m.group(1)}'"}
    # select option
    m = re.match(r"select\s+(.+?)\s+(?:from|in|under|for)\s+(?:the\s+)?(.+)", low)
    if m and not re.search(r"check ?box", low):
        f = ctx.field(m.group(2), path)
        if f:
            opt = m.group(1).strip("'\" ")
            opts = f["field"].get("options") or []
            best = max(opts, key=lambda o: similarity(opt, o.get("text")), default=None) if opts else None
            if best and similarity(opt, best.get("text")) >= 0.6:
                return {**step, "action": "fill", "field": f["field"]["name"], "label": f["field"].get("label"),
                        "value": best["value"], "ok": True}
            return {**step, "action": "manual", "ok": False, "why": f"'{opt}' is not an option of {f['field'].get('label')}"}
    # tick / check a checkbox
    m = re.match(r"(?:tick|check|select|accept|agree to)\s+(?:the\s+)?(.+?)(?:\s+check ?box)?$", low)
    if m and (re.search(r"check ?box|tick|declaration|terms|agree|accept", low)):
        f = ctx.field(m.group(1), path)
        if not f:
            f = next((x for x in ctx.fields if x["path"] == path and x["field"].get("type") == "checkbox"), None)
        if f:
            return {**step, "action": "fill", "field": f["field"]["name"], "label": f["field"].get("label"), "value": "on",
                    "ok": True}
    # enter / type
    m = (re.match(r"(?:enter|type|input|key in|fill(?: in)?|provide|give)\s+(.+?)\s+(?:in|into|for|in the|as the)\s+(?:the\s+)?(.+?)(?:\s+field|\s+box|\s+textbox)?$", low)
         or None)
    m2 = re.match(r"(?:enter|type|input|fill(?: in)?|provide)\s+(?:the\s+)?(.+?)\s+(?:as|=|:|with)\s+(.+)$", low)
    m3 = re.match(r"(?:enter|type|input|fill(?: in)?|provide)\s+(?:the\s+)?(?:valid\s+)?([a-z][a-z ]{2,40})$", low)
    if m or m2 or m3:
        candidates = []
        if m2:
            candidates.append((m2.group(1), t[m2.start(2):m2.end(2)]))
        if m:
            candidates.append((m.group(2), t[m.start(1):m.end(1)]))
        if m3:
            candidates.append((m3.group(1), "valid"))
        for label, raw in candidates:
            f = ctx.field(label, path)
            if f:
                v = _value(raw, data, f)
                if v is None:
                    return {**step, "action": "manual", "ok": False, "why": "the value is described, not given"}
                if (f["field"].get("type") or "") == "password":
                    return {**step, "action": "skip", "ok": True, "why": "passwords come from the saved login session"}
                return {**step, "action": "fill", "field": f["field"]["name"], "label": f["field"].get("label"),
                        "value": v, "ok": True}
        return {**step, "action": "manual", "ok": False, "why": "no field on the current screen matches"}
    # click
    m = re.match(r"(?:click|press|tap|hit)\s+(?:on\s+)?(?:the\s+)?(.+?)(?:\s+(button|link|tab|icon))?$", low)
    if m:
        target = t[m.start(1):m.end(1)].strip("'\" ")
        if (m.group(2) == "link" or not m.group(2)) and ctx.screen(target) and target.lower() in ctx.links:
            p = ctx.links[target.lower()]
            return {**step, "action": "click", "target": target, "then_path": p, "ok": True}
        if re.search(r"\b(first|second|any|an?)\b.*\b(application|record|row|item)\b", target.lower()):
            return {**step, "action": "manual", "ok": False, "why": "which record to click is not specified"}
        return {**step, "action": "click", "target": target, "ok": True}
    return {**step, "action": "manual", "ok": False, "why": "not a recognised step"}


def convert_expected(text: str, ctx: Context, state: dict) -> dict:
    t = text.strip()
    low = t.lower()
    step = {"text": t}
    q = QUOTED.search(t)
    if re.search(r"access denied|not authori[sz]ed|forbidden|cannot access|is blocked|is denied|unauthori[sz]ed", low):
        return {**step, "action": "expect_denied", "ok": True}
    if re.search(r"\b(e-?mail|mail|sms|text message)\b", low) and re.search(r"\b(received|receives|sent|delivered|arrives?|gets?)\b", low):
        kind = "sms" if re.search(r"\b(sms|text message)\b", low) else "email"
        addr = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", t) if kind == "email" else re.search(r"\b\d{10}\b", t)
        acc = ctx.project.account(state.get("role") or "") or {}
        to = addr.group(0) if addr else acc.get("email" if kind == "email" else "mobile")
        if not to:
            return {**step, "action": "manual", "ok": False,
                    "why": f"give the {'address' if kind == 'email' else 'mobile number'} or add it to the role in project.yaml"}
        return {**step, "action": "expect_email" if kind == "email" else "expect_sms", "to": to, "ok": True}
    if re.search(r"error|invalid|validation message|warning", low) and not q:
        return {**step, "action": "expect_error", "ok": True}
    if q:
        return {**step, "action": "expect_text", "value": q.group(1), "ok": True}
    m = re.search(r"(?:navigated|redirected|taken|lands?|moved)\s+to\s+(?:the\s+)?(.+?)(?:\s+page|\s+screen)?$", low)
    if m:
        p = ctx.screen(m.group(1), state.get("role"))
        if p:
            return {**step, "action": "expect_path", "path": p, "ok": True}
    m = re.match(r"(?:the\s+)?(.+?)\s+(?:page|screen)\s+(?:is|should be|gets?)\s+(?:displayed|shown|opened|loaded)", low)
    if m:
        return {**step, "action": "expect_page", "value": m.group(1).strip(), "ok": True}
    if re.search(r"success|submitted|saved|created|registered", low):
        return {**step, "action": "expect_success", "ok": True}
    m = re.search(r"status\s+(?:is|should be|changes to|becomes|shows)\s+(\w+)", low)
    if m:
        return {**step, "action": "expect_text", "value": m.group(1), "ok": True}
    return {**step, "action": "manual", "ok": False, "why": "the expected result is not specific enough to check"}


def convert(case: dict, ctx: Context) -> dict:
    data = _data(case.get("data") or "")
    role = ctx.role_of(case.get("role") or "") or ctx.role_of(case.get("pre") or "")
    state = {"role": role, "path": None}
    steps = []
    for line in _split(case.get("pre") or ""):
        s = convert_step(line, ctx, state, data)
        if s["action"] in ("session", "goto"):
            steps.append(s)
    steps += [convert_step(x, ctx, state, data) for x in case["steps"]]
    steps += [convert_expected(x, ctx, state) for x in case["expected"]]
    role = state.get("role") or role or next(iter(ctx.roles), "anonymous")
    real = [s for s in steps if s["action"] not in ("session", "skip")]
    done = [s for s in real if s["ok"]]
    coverage = round(len(done) / len(real), 2) if real else 0.0
    start = next((s["path"] for s in steps if s["action"] == "goto"), None)
    reqs = re.findall(r"\b(?:FR|NFR|TBL|SRS|BR|REQ)[-_ ]?\d+\b", (case.get("req") or "") + " " + (case.get("title") or ""))
    return {"role": role, "start": start, "steps": steps, "coverage": coverage,
            "req_ids": sorted({r.replace("_", "-").replace(" ", "-").upper() for r in reqs})}


def import_file(project: Project, store: Store, path: Path) -> dict:
    cases = read_cases(path)
    ctx = Context(project, store)
    live.emit("importer", "start", f"Reading {path.name}: {len(cases)} manual test case(s)", file=path.name)
    ready = review = 0
    for c in cases:
        conv = convert(c, ctx)
        status = "ready" if conv["coverage"] == 1.0 else "review"
        ready += status == "ready"
        review += status == "review"
        old = store.one("SELECT status FROM manual_cases WHERE id=?", [c["id"]])
        if old and old["status"] in ("approved", "rejected"):
            status = old["status"]
        store.insert("manual_cases", {"id": c["id"], "title": c["title"] or c["id"], "role": conv["role"],
                                      "steps": "\n".join(c["steps"]), "expected": "\n".join(c["expected"]), "converted": conv,
                                      "coverage": conv["coverage"], "status": status, "source_file": path.name,
                                      "created_at": now()}, replace=True)
        live.emit("importer", "case", f"{c['id']}: {c['title'] or ''} - {conv['coverage']:.0%} of steps automated",
                  case=c["id"], level="ok" if conv["coverage"] == 1.0 else "warn")
    summary = {"file": path.name, "cases": len(cases), "ready": ready, "review": review}
    live.emit("importer", "summary", f"{len(cases)} case(s): {ready} fully automated, {review} need review", **summary)
    return summary


def set_status(store: Store, ids: list[str], status: str) -> int:
    for i in ids:
        store.update("manual_cases", "id", i, {"status": status})
    return len(ids)
