"""AgentQA Studio web UI: pipeline control and the three human gates.

Long stages run as separate `python -m agentqa ...` processes, so the UI stays
responsive and a crash in one stage cannot take the UI down.
"""
from __future__ import annotations

import os
import re
import shutil
from contextlib import contextmanager
from pathlib import Path

import yaml
from urllib.parse import quote
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from agentqa import __version__, readiness
from agentqa.config import Project, init_project
from agentqa.store import Store

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
MAX_ROW_ID = 2 ** 31 - 1          # a row id SQLite can compare (a larger one is "not found", never a crash)

app = FastAPI(title="AgentQA Studio")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
tpl = Jinja2Templates(directory=HERE / "templates")
tpl.env.globals["version"] = __version__


def _ts(value) -> str:
    from datetime import datetime
    try:
        return datetime.fromtimestamp(float(value)).strftime("%d %b %H:%M:%S")
    except (TypeError, ValueError):
        return str(value or "")


tpl.env.filters["ts"] = _ts

# ---------------------------------------------------------------------------
# Projects, jobs and live recordings live in agentqa.orchestrator (M0.5); these wrappers keep the
# dashboard's names and its HTTP errors.
# ---------------------------------------------------------------------------
from agentqa.orchestrator import Busy, NotFound  # noqa: E402
from agentqa.orchestrator import jobs as _jobs, live as _live, projects as _proj  # noqa: E402

PROCS = _jobs.PROCS
_pid_alive = _jobs.pid_alive
_running = _jobs.running
_prune_live = _jobs.prune_live
_projects = _proj.list_projects
_sessions = _live.sessions


def _open(slug: str) -> tuple[Project, Store]:
    try:
        return _proj.open_project(slug)
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from exc


def _spawn(p: Project, s: Store, args: list[str], label: str, headed: bool = False, shots: bool | None = None) -> int:
    try:
        return _jobs.spawn(p, s, args, label, headed=headed, shots=shots)
    except Busy as exc:
        raise HTTPException(409, str(exc)) from exc


def _session_dir(p: Project, session: str) -> Path:
    try:
        return _live.session_dir(p, session)
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from exc


PROJECTS = _proj.projects_dir()

ICONS = {"analyze": "doc", "write": "list", "explore": "search", "reconcile": "scale", "design": "layers", "generate": "code",
         "run": "play", "exploratory": "compass", "security": "shield", "triage": "bug", "heal": "wrench", "report": "report"}
STAGE_INFO = [
    ("analyze", "Requirement Analyst", "Reads the requirement documents into numbered requirements and testable rules"),
    ("explore", "Explorer", "Logs in as every role (in English) and maps each screen, form and link"),
    ("reconcile", "Reconciler", "Compares SRS with the app; raises questions where they disagree"),
    ("write", "Requirement Writer", "Rewrites each requirement into clear wording, steps and acceptance criteria (AI model when set up)"),
    ("design", "Planner + Designer", "Builds the risk-ranked plan and test cases"),
    ("generate", "Script Generator", "Writes pytest + Playwright code for approved cases"),
    ("run", "Executor", "Runs the suite in parallel browsers, keeps evidence"),
    ("exploratory", "Exploratory Tester", "Wanders like a curious user: odd input, other roles' addresses, JS errors, "
                                          "security headers"),
    ("security", "Security Scanner", "OWASP ZAP inspects every screen as each role; passive unless active scans are on"),
    ("triage", "Triage + Bug Reporter", "Groups failures into defect drafts"),
    ("heal", "Healer", "Proposes fixes for tests broken by UI changes"),
    ("report", "Reporter", "HTML report, traceability matrix and defect CSV"),
]


from agentqa.login_flow import account_status  # noqa: E402  (re-exported for templates and the master plan)


def _accounts_missing(p: Project) -> int:
    """Roles that cannot log in yet because something is missing (a password, or a mobile number for an OTP login)."""
    try:
        return sum(1 for role in p.roles() if not account_status(p, role)["ready"])
    except Exception:  # noqa: BLE001
        return 0


def _ctx(request: Request, slug: str, page: str, **extra) -> dict:
    p, s = _open(slug)
    counts = {
        "questions": s.scalar("SELECT COUNT(*) FROM questions WHERE status='open'") or 0,
        "drafts": s.scalar("SELECT COUNT(*) FROM defects WHERE status='draft'") or 0,
        "heals": s.scalar("SELECT COUNT(*) FROM heals WHERE status='proposed'") or 0,
        "proposed": s.scalar("SELECT COUNT(*) FROM cases WHERE status='proposed'") or 0,
        "apis": s.scalar("SELECT COUNT(DISTINCT pattern) FROM endpoints WHERE status BETWEEN 200 AND 299") or 0,
        "manual_review": s.scalar("SELECT COUNT(*) FROM manual_cases WHERE status IN ('ready','review')") or 0,
        "visual": s.scalar("SELECT COUNT(*) FROM visual WHERE status='changed'") or 0,
        "zap": s.scalar("SELECT COUNT(DISTINCT alert) FROM zap_alerts WHERE run_id=? AND risk IN ('High','Medium')",
                        [s.get_meta("zap_run") or "-"]) or 0,
        "sync_errors": s.scalar("SELECT COUNT(*) FROM sync_log WHERE ok=0 AND at >= ?",
                                [(s.get_meta("tracker_sync") or {}).get("at") or "9"]) or 0,
        "doctor_fail": (s.get_meta("doctor") or {}).get("fail") or 0,
        "accounts_missing": _accounts_missing(p),
        "functional": s.scalar("SELECT COUNT(*) FROM cases WHERE type='functional'") or 0,
    }
    running = _running(s)
    try:
        from agentqa import masterplan
        nxt = masterplan.compute(p, s, running)["next"]
    except Exception:  # noqa: BLE001 - the banner is a convenience, never a reason for a page to fail
        nxt = None
    return {"request": request, "slug": slug, "project": p, "store": s, "page": page, "counts": counts,
            "running": running, "next_step": nxt, **extra}


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return tpl.TemplateResponse(request, "home.html", {"projects": _projects(), "projects_dir": PROJECTS})


@app.post("/new")
def new_project(name: str = Form(...), url: str = Form(...)):
    name, url = name.strip(), url.strip()
    if not name:
        raise HTTPException(400, "Give the project a name")
    if not re.match(r"^https?://[^\s/]+", url):
        raise HTTPException(400, "The portal address must be a full URL starting with http:// or https://")
    problem = _proj.address_problem(url)                            # user:password@ in the address (M1.3 #19)
    if problem:
        raise HTTPException(422, problem)
    slug = "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")[:40] or "project"
    if (PROJECTS / slug / "project.yaml").exists():
        return RedirectResponse(f"/p/{slug}", status_code=303)
    init_project(PROJECTS / slug, name, url)
    return RedirectResponse(f"/p/{slug}/testdata?add=1", status_code=303)


@app.post("/demo")
def make_demo():
    dest = PROJECTS / "demo"
    dest.mkdir(exist_ok=True)
    (dest / "srs").mkdir(exist_ok=True)
    shutil.copy(ROOT / "demo" / "project.yaml", dest / "project.yaml")
    for f in (ROOT / "demo" / "srs").glob("*.docx"):
        shutil.copy(f, dest / "srs" / f.name)
    (dest / "imports").mkdir(exist_ok=True)
    if (ROOT / "demo" / "manual_tests.xlsx").exists():
        shutil.copy(ROOT / "demo" / "manual_tests.xlsx", dest / "imports" / "manual_tests.xlsx")
    return RedirectResponse("/p/demo", status_code=303)


@app.get("/p/{slug}", response_class=HTMLResponse)
def overview(request: Request, slug: str):
    ctx = _ctx(request, slug, "overview")
    s, p = ctx["store"], ctx["project"]
    plan = s.one("SELECT * FROM plan WHERE id=1")
    run = s.one("SELECT * FROM runs WHERE status='done' ORDER BY started_at DESC LIMIT 1")
    jobs = s.all("SELECT * FROM jobs ORDER BY id DESC LIMIT 8")
    defects = {d["severity"]: d["n"] for d in s.all(
        "SELECT severity, COUNT(*) n FROM defects WHERE status NOT IN ('rejected','resolved') GROUP BY severity")}
    live_root = p.state / "live"
    live_ids = {d.name for d in live_root.iterdir()} if live_root.exists() else set()
    covered = {x for c in s.all("SELECT req_ids FROM cases") for x in (c["req_ids"] or [])}
    k = {
        "requirements": s.scalar("SELECT COUNT(*) FROM requirements") or 0, "covered": len(covered),
        "screens": s.scalar("SELECT COUNT(DISTINCT path) FROM screens") or 0,
        "roles": s.scalar("SELECT COUNT(DISTINCT role) FROM screens") or 0,
        "apis": ctx["counts"]["apis"], "documented": s.scalar("SELECT COUNT(*) FROM endpoints WHERE documented=1") or 0,
        "cases": s.scalar("SELECT COUNT(*) FROM cases") or 0,
        "approved": s.scalar("SELECT COUNT(*) FROM cases WHERE status='approved'") or 0,
        "types": s.scalar("SELECT COUNT(DISTINCT type) FROM cases") or 0,
        "defects": sum(defects.values()),
        "visual": s.scalar("SELECT COUNT(*) FROM visual") or 0, "visual_changed": ctx["counts"]["visual"],
        "manual": s.scalar("SELECT COUNT(*) FROM manual_cases") or 0,
        "manual_auto": s.scalar("SELECT COUNT(*) FROM manual_cases WHERE status='approved'") or 0,
    }
    return tpl.TemplateResponse(request, "overview.html", {
        **ctx, "plan": plan, "run": run, "jobs": jobs, "defects": defects, "live_ids": live_ids, "k": k,
        "r": readiness.compute(p, s), "trend": readiness.trend(s), "agents": _agents(p, s, ctx["running"]),
        "sessions": _sessions(p, s), "jobs_by_id": {j["id"]: j for j in s.all("SELECT * FROM jobs ORDER BY id DESC LIMIT 40")},
        "srs_files": len([f for f in p.srs_dir.iterdir() if f.is_file()])})


def _agents(p: Project, s: Store, running: dict | None) -> list[dict]:
    m = {k: s.get_meta(k) for k in ("analyze", "explore", "triage", "exploratory", "zap")}
    run = s.one("SELECT * FROM runs WHERE status='done' ORDER BY started_at DESC LIMIT 1")
    rules = s.scalar("SELECT COUNT(*) FROM rules") or 0
    stats = {
        "analyze": f"{m['analyze']['requirements']} requirements, {m['analyze']['rules']} rules" if m["analyze"] else "",
        "explore": f"{sum(m['explore'].values())} screen visits" if m["explore"] else "",
        "reconcile": (f"{rules} rules, {s.scalar('SELECT COUNT(*) FROM questions WHERE status=' + chr(39) + 'open' + chr(39))} "
                      f"open question(s)") if s.scalar("SELECT COUNT(*) FROM rules WHERE status IS NOT NULL") else "",
        "write": (lambda w: f"{w['requirements']} rewritten ({w['by_model']} by the model)" if w else "")(s.get_meta("writer")),
        "design": f"{s.scalar('SELECT COUNT(*) FROM cases')} cases" if s.scalar("SELECT COUNT(*) FROM cases") else "",
        "generate": (f"{len(list(p.tests_dir.glob('test_*.py')))} test files" if p.tests_dir.exists()
                     and any(p.tests_dir.glob("test_*.py")) else ""),
        "run": f"{run['passed']} of {run['total']} passed" if run else "",
        "exploratory": (f"{m['exploratory']['steps']} steps, {m['exploratory']['findings']} findings"
                        if m["exploratory"] else ""),
        "security": ((f"{m['zap']['alerts']} alerts, {m['zap']['findings']} for triage" if "alerts" in m["zap"]
                      else "skipped: ZAP not installed") if m["zap"] else ""),
        "triage": f"{s.scalar('SELECT COUNT(*) FROM defects WHERE status NOT IN (' + chr(39) + 'rejected' + chr(39) + ')')} defects"
                  if m["triage"] else "",
        "heal": f"{s.scalar('SELECT COUNT(*) FROM heals WHERE status=' + chr(39) + 'proposed' + chr(39))} proposal(s)"
                if s.scalar("SELECT COUNT(*) FROM heals") or (run and m["triage"]) else "",
        "report": "report ready" if (p.reports_dir / "report.html").exists() else "",
    }
    active = running["stage"] if running else None
    return [{"key": key, "name": name, "desc": desc, "icon": ICONS.get(key, "spark"), "stat": stats.get(key, ""),
             "done": bool(stats.get(key)), "active": active == key} for key, name, desc in STAGE_INFO]


@app.get("/p/{slug}/masterplan", response_class=HTMLResponse)
def masterplan_page(request: Request, slug: str):
    from agentqa import masterplan
    ctx = _ctx(request, slug, "masterplan")
    m = masterplan.compute(ctx["project"], ctx["store"], ctx["running"])
    return tpl.TemplateResponse(request, "masterplan.html", {**ctx, "m": m})


@app.post("/p/{slug}/run/{stage}")
def run_stage(slug: str, stage: str, policy: str = Form(""), auto_approve: str = Form(""), watch: str = Form(""),
              headed: str = Form(""), only: str = Form("")):
    p, s = _open(slug)
    if stage == "run" and only.strip() == "functional":
        args = ["run", "--type", "functional"]
    elif stage == "run" and only.strip():
        args = ["run", "--only", *only.split()]
    elif stage == "pipeline":
        args = ["pipeline"] + (["--policy", policy] if policy else []) + (["--auto-approve"] if auto_approve else [])
    elif stage == "continue":
        args = ["pipeline", "--from", "generate"]
    elif stage in [x[0] for x in STAGE_INFO]:
        args = [stage] + (["--policy", policy] if policy and stage == "reconcile" else [])
    else:
        raise HTTPException(404)
    job_id = _spawn(p, s, args, stage, headed=bool(headed))
    if watch:
        return RedirectResponse(f"/p/{slug}/live?s=job-{job_id}-{stage}", status_code=303)
    return RedirectResponse(f"/p/{slug}", status_code=303)


@app.get("/p/{slug}/execution", response_class=HTMLResponse)
def execution_page(request: Request, slug: str, status: str = "", module: str = ""):
    from agentqa import contracts, execution
    ctx = _ctx(request, slug, "execution")
    p, s = ctx["project"], ctx["store"]
    sm = execution.summary(p, s)
    shown = [r for r in sm["rows"] if (not status or r["status"] == status) and (not module or r["module"] == module)]
    pl = s.one("SELECT pipeline FROM stage_runs WHERE pipeline LIKE 'pl-%' ORDER BY id DESC LIMIT 1")
    stages = s.all("SELECT * FROM stage_runs WHERE pipeline=? ORDER BY id", [pl["pipeline"]]) if pl else []
    singles = s.all("SELECT * FROM stage_runs WHERE pipeline='single' ORDER BY id DESC LIMIT 6")
    return tpl.TemplateResponse(request, "execution.html", {
        **ctx, "sm": sm, "shown": shown[:400], "shown_n": len(shown), "fstatus": status, "fmodule": module,
        "statuses": execution.ORDER, "stages": stages, "singles": singles, "pipeline_id": pl["pipeline"] if pl else None,
        "agents": contracts.AGENTS, "may_not_change": contracts.MAY_NOT_CHANGE})


@app.get("/p/{slug}/changes", response_class=HTMLResponse)
def changes_page(request: Request, slug: str):
    ctx = _ctx(request, slug, "execution")
    rows = ctx["store"].all("SELECT * FROM change_log ORDER BY id DESC LIMIT 500")
    return tpl.TemplateResponse(request, "changes.html", {**ctx, "rows": rows})


@app.post("/p/{slug}/execute")
async def execute(request: Request, slug: str):
    from agentqa import execution
    p, s = _open(slug)
    form = await request.form()
    scope, value = str(form.get("scope") or ""), str(form.get("value") or "")
    if scope == "all":
        args, label = ["run", "--all-approved"], "run"
    elif scope == "regression":
        args, label = ["pipeline", "--from", "generate"], "pipeline"
    elif scope == "resume":
        args, label = ["pipeline", "--resume"], "pipeline"
    else:
        try:
            ids = execution.select(p, s, scope, value, [str(x) for x in form.getlist("ids")])
        except ValueError:
            raise HTTPException(400, f"Unknown run scope '{scope}'") from None
        if not ids:
            raise HTTPException(400, "No approved test case matches. Approve cases on the Test plan page first.")
        args, label = ["run", "--only", *ids], "run"
    job_id = _spawn(p, s, args, label, headed=bool(form.get("headed")))
    if form.get("watch"):
        return RedirectResponse(f"/p/{slug}/live?s=job-{job_id}-{label}", status_code=303)
    return RedirectResponse(f"/p/{slug}/execution", status_code=303)


# ---------------------------------------------------------------------------
# Live View
# ---------------------------------------------------------------------------

@app.get("/p/{slug}/live", response_class=HTMLResponse)
def live_page(request: Request, slug: str, s: str = ""):  # noqa: A002
    ctx = _ctx(request, slug, "live")
    p, store = ctx["project"], ctx["store"]
    sessions = _sessions(p, store)
    ids = [x["id"] for x in sessions]
    # the session to show: the one asked for; else the run in progress; else the newest one that has something to
    # show (a job that wrote no events, such as a tracker sync, would otherwise open an empty player)
    if s in ids:
        current = s
    else:
        running_ids = [x["id"] for x in sessions if x["running"]]
        with_events = [x["id"] for x in sessions if x["shots"]
                       or any(f.stat().st_size > 0 for f in (p.state / "live" / x["id"]).glob("events-*.jsonl"))]
        current = (running_ids or with_events or ids or [""])[0]
    roles = list(p.roles()) + ["anonymous"]
    return tpl.TemplateResponse(request, "live.html", {**ctx, "sessions": sessions, "current": current, "roles": roles})


@app.get("/p/{slug}/live/{session}/events")
def live_events(slug: str, session: str, cursor: str = ""):
    import base64
    import json as _json
    p, store = _open(slug)
    d = _session_dir(p, session)
    try:
        offsets = _json.loads(base64.urlsafe_b64decode(cursor.encode()).decode()) if cursor else {}
    except Exception:  # noqa: BLE001
        offsets = {}
    events = []
    for f in sorted(d.glob("events-*.jsonl")):
        start = int(offsets.get(f.name, 0))
        with f.open("rb") as fh:
            fh.seek(start)
            chunk = fh.read(4_000_000)
        end = chunk.rfind(b"\n") + 1
        for line in chunk[:end].splitlines():
            try:
                events.append(_json.loads(line))
            except ValueError:
                continue
        offsets[f.name] = start + end
    events.sort(key=lambda e: (e.get("t", 0), e.get("seq", 0)))
    running = any(x["id"] == session and x["running"] for x in _sessions(p, store))
    token = base64.urlsafe_b64encode(_json.dumps(offsets).encode()).decode()
    return {"events": events, "cursor": token, "running": running}


@app.get("/p/{slug}/live-sessions")
def live_sessions(slug: str):
    p, store = _open(slug)
    return {"sessions": _sessions(p, store)}


@app.get("/p/{slug}/live/{session}/shots/{name}")
def live_shot(slug: str, session: str, name: str):
    p, _ = _open(slug)
    d = _session_dir(p, session)
    f = (d / "shots" / Path(name).name)
    if not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@app.get("/p/{slug}/job/{job_id}/log", response_class=PlainTextResponse)
def job_log(slug: str, job_id: int):
    _, s = _open(slug)
    job = s.one("SELECT * FROM jobs WHERE id=?", [job_id])
    if not job:
        raise HTTPException(404)
    text = Path(job["log_path"]).read_text(encoding="utf-8", errors="replace") if Path(job["log_path"]).exists() else ""
    return PlainTextResponse(f"status: {job['status']}\n" + text[-12000:])


@app.get("/p/{slug}/config", response_class=HTMLResponse)
def config_page(request: Request, slug: str, error: str = ""):
    ctx = _ctx(request, slug, "config")
    text = ctx["project"].config_path.read_text(encoding="utf-8")
    return tpl.TemplateResponse(request, "config.html", {**ctx, "text": text, "error": error})


@app.post("/p/{slug}/config")
def save_config(slug: str, text: str = Form(...)):
    p, _ = _open(slug)
    try:
        data = yaml.safe_load(text)
        if not isinstance(data, dict) or "base_url" not in data:
            raise ValueError("project.yaml must be a mapping with at least base_url")
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/p/{slug}/config?error={str(exc)[:200]}", status_code=303)
    p.config_path.write_text(text, encoding="utf-8")
    return RedirectResponse(f"/p/{slug}/config", status_code=303)


# ---------------------------------------------------------------------------
# SRS, app map, questions
# ---------------------------------------------------------------------------

@app.get("/p/{slug}/srs", response_class=HTMLResponse)
def srs_page(request: Request, slug: str):
    ctx = _ctx(request, slug, "srs")
    s, p = ctx["store"], ctx["project"]
    files = sorted(x.name for x in p.srs_dir.iterdir() if x.is_file())
    reqs = s.all("SELECT * FROM requirements ORDER BY seq")
    rules = s.all("SELECT * FROM rules ORDER BY id")
    by_req: dict[str, list] = {}
    for r in rules:
        by_req.setdefault(r["req_id"], []).append(r)
    from agentqa.agents import requirements as reqs_agent
    from agentqa.documents import SUPPORTED
    docs = {d["name"]: d for d in s.all("SELECT * FROM documents")}
    review = s.all("SELECT * FROM segments WHERE disposition='possibly missed' ORDER BY id")
    cov = reqs_agent.coverage(p, s) if reqs else {}
    disp_counts: dict[str, int] = {}
    for r in reqs:
        disp_counts[r.get("disposition") or "gap"] = disp_counts.get(r.get("disposition") or "gap", 0) + 1
    return tpl.TemplateResponse(request, "srs.html", {**ctx, "files": files, "reqs": reqs, "by_req": by_req,
                                                      "orphan": by_req.get(None, []), "docs": docs, "review": review,
                                                      "cov": cov, "dispositions": reqs_agent.DISPOSITIONS,
                                                      "disp_counts": disp_counts, "accept": ",".join(sorted(SUPPORTED))})


@app.post("/p/{slug}/srs")
async def upload_srs(slug: str, file: list[UploadFile] = File(...)):
    """Same checks as the new API (name, type, size, zip bombs): both UIs go through intake.save_document."""
    from agentqa.orchestrator import intake
    p, _ = _open(slug)
    bad = []
    for up in file:
        try:
            intake.save_document(p, up.filename or "srs.docx", await up.read())
        except intake.Unsupported:
            bad.append(Path(up.filename or "srs.docx").name)
        except intake.TooLarge as exc:
            raise HTTPException(413, str(exc)) from exc
    if bad:
        raise HTTPException(400, f"Not a supported document: {', '.join(bad)}")
    return RedirectResponse(f"/p/{slug}/srs", status_code=303)


@app.post("/p/{slug}/srs/disposition")
def srs_disposition(slug: str, req_id: str = Form(...), disposition: str = Form(...), note: str = Form("")):
    from agentqa.agents import requirements as reqs_agent
    _, s = _open(slug)
    reqs_agent.set_disposition(s, req_id, disposition, note)
    return RedirectResponse(f"/p/{slug}/srs#{req_id}", status_code=303)


@app.post("/p/{slug}/srs/segment/{sid}")
def srs_segment(slug: str, sid: int, disposition: str = Form(...)):
    _, s = _open(slug)
    if disposition not in ("context", "out of scope"):
        raise HTTPException(400)
    s.update("segments", "id", sid, {"disposition": disposition, "note": "marked by a person"})
    return RedirectResponse(f"/p/{slug}/srs#review", status_code=303)


@app.get("/p/{slug}/rtm.xlsx")
def rtm_xlsx(slug: str):
    from agentqa.agents import requirements as reqs_agent
    p, s = _open(slug)
    _, x = reqs_agent.write_rtm(p, s)
    return FileResponse(x, filename=f"{p.name.replace(' ', '-')}-traceability.xlsx")


@app.post("/p/{slug}/srs/delete")
def delete_srs(slug: str, name: str = Form(...)):
    p, _ = _open(slug)
    target = (p.srs_dir / Path(name).name)
    if target.exists():
        target.unlink()
    return RedirectResponse(f"/p/{slug}/srs", status_code=303)


@app.get("/p/{slug}/appmap", response_class=HTMLResponse)
def appmap(request: Request, slug: str):
    ctx = _ctx(request, slug, "appmap")
    p = ctx["project"]
    screens = ctx["store"].all("SELECT * FROM screens ORDER BY path, role")
    paths: dict[str, list] = {}
    for sc in screens:
        paths.setdefault(sc["path"], []).append(sc)
    roles = sorted({sc["role"] for sc in screens})
    shown = {}
    if p.vault.path.exists():
        for r in list(p.roles()):
            try:
                shown[r] = len(p.vault.nav_hints(r))
            except Exception:  # noqa: BLE001
                shown[r] = 0
    return tpl.TemplateResponse(request, "appmap.html", {**ctx, "paths": paths, "roles": roles,
                                                         "nav_roles": list(p.roles()), "shown": shown})


@app.post("/p/{slug}/appmap/teach-nav")
def appmap_teach_nav(slug: str, role: str = Form(...)):
    p, s = _open(slug)
    if role not in p.roles():
        raise HTTPException(400, "Unknown role")
    job_id = _spawn(p, s, ["teach-nav", "--role", role], f"teach-nav-{role}", headed=True)
    return RedirectResponse(f"/p/{slug}/live?s=job-{job_id}-teach-nav-{role}", status_code=303)


@app.get("/p/{slug}/questions", response_class=HTMLResponse)
def questions(request: Request, slug: str):
    ctx = _ctx(request, slug, "questions")
    s = ctx["store"]
    order = "CASE priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END, id"
    return tpl.TemplateResponse(request, "questions.html", {
        **ctx, "open": s.all(f"SELECT * FROM questions WHERE status='open' ORDER BY {order}"),
        "answered": s.all("SELECT * FROM questions WHERE status='answered' ORDER BY answered_at DESC")})


@app.post("/p/{slug}/questions/{qid}")
def answer(slug: str, qid: int, choice: int = Form(...), value: str = Form("")):
    from agentqa.agents.reconciler import answer_question
    _, s = _open(slug)
    answer_question(s, qid, choice, value)
    return RedirectResponse(f"/p/{slug}/questions", status_code=303)


@app.post("/p/{slug}/questions/{qid}/reopen")
def reopen(slug: str, qid: int):
    _, s = _open(slug)
    s.update("questions", "id", qid, {"status": "open", "answer": None, "answer_value": None})
    return RedirectResponse(f"/p/{slug}/questions", status_code=303)


# ---------------------------------------------------------------------------
# Plan gate, results, defects gate, heals
# ---------------------------------------------------------------------------

@app.get("/p/{slug}/plan", response_class=HTMLResponse)
def plan_page(request: Request, slug: str, type: str = ""):  # noqa: A002
    ctx = _ctx(request, slug, "plan")
    s = ctx["store"]
    plan = s.one("SELECT * FROM plan WHERE id=1")
    cases = s.all("SELECT * FROM cases " + ("WHERE type=? " if type else "") + "ORDER BY seq", [type] if type else [])
    types = s.all("SELECT type, COUNT(*) n, SUM(status='approved') a FROM cases GROUP BY type ORDER BY type")
    gaps = {
        "untested": [r["id"] for r in s.all("SELECT id FROM requirements WHERE disposition='gap' ORDER BY seq")],
        "clarify": [r["id"] for r in s.all("SELECT id FROM requirements WHERE disposition='clarify' ORDER BY seq")],
        "unread": s.all("SELECT name, status, detail FROM documents WHERE status != 'read'"),
        "missed": s.scalar("SELECT COUNT(*) FROM segments WHERE disposition='possibly missed'") or 0,
        "workflow": s.get_meta("workflow_gaps") or [],
        "production": s.get_meta("production_skipped") or [],
    }
    return tpl.TemplateResponse(request, "plan.html", {**ctx, "plan": plan, "cases": cases, "types": types, "ftype": type,
                                                       "gaps": gaps})


@app.post("/p/{slug}/plan")
async def plan_action(request: Request, slug: str):
    from agentqa.agents import designer
    _, s = _open(slug)
    form = await request.form()
    action = form.get("action")
    ids = form.getlist("ids")
    if action == "approve_all":
        designer.approve(s)
    elif action == "approve" and ids:
        designer.approve(s, case_ids=ids)
    elif action == "reject" and ids:
        designer.approve(s, case_ids=ids, reject=True)
    elif action == "reset" and ids:
        for cid in ids:
            s.update("cases", "id", cid, {"status": "proposed"})
    return RedirectResponse(f"/p/{slug}/plan", status_code=303)


@app.get("/p/{slug}/functional", response_class=HTMLResponse)
def functional_page(request: Request, slug: str, module: str = "", status: str = "", srs: int = 1):
    from agentqa import case_export
    ctx = _ctx(request, slug, "functional")
    p, s = ctx["project"], ctx["store"]
    rows = case_export.rows(p, s, include_srs=bool(srs))
    mods: dict[str, dict] = {}
    for r in rows:
        m = mods.setdefault(r["module"], {"n": 0, "Passed": 0, "Failed": 0, "Blocked": 0, "Not Run": 0})
        m["n"] += 1
        m[r["status"]] = m.get(r["status"], 0) + 1
    totals = {k: sum(m.get(k, 0) for m in mods.values()) for k in ("n", "Passed", "Failed", "Blocked", "Not Run")}
    shown = [r for r in rows if (not module or r["module"] == module) and (not status or r["status"] == status)]
    reqs = {x.strip() for r in rows for x in r["reqs"].split(",") if x.strip()}
    req_total = s.scalar("SELECT COUNT(*) FROM requirements") or 0
    proposed = sum(1 for r in rows if r["approved"] == "proposed" and r["type"] == "functional")
    accounts = bool(p.vault.path.exists() and p.vault.load()["login_steps"])
    return tpl.TemplateResponse(request, "functional.html", {
        **ctx, "rows": shown, "all_n": len(rows), "mods": mods, "totals": totals, "fmodule": module, "fstatus": status,
        "srs": srs, "req_covered": len(reqs), "req_total": req_total, "proposed": proposed, "accounts": accounts})


@app.post("/p/{slug}/functional/approve")
def functional_approve(slug: str):
    from agentqa.agents import designer
    _, s = _open(slug)
    designer.approve(s, case_types=["functional"])
    return RedirectResponse(f"/p/{slug}/functional", status_code=303)


@app.get("/p/{slug}/functional.xlsx")
def functional_xlsx(slug: str, srs: int = 1):
    from agentqa import case_export
    p, s = _open(slug)
    name = re.sub(r"[^A-Za-z0-9]+", "-", p.name).strip("-") or "project"
    return Response(case_export.workbook(p, s, include_srs=bool(srs), all_types=False),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}-functional-test-cases.xlsx"'})


@app.get("/p/{slug}/testcases.xlsx")
def testcases_xlsx(slug: str):
    """Every prepared test case (all types) in the standard template."""
    from agentqa import case_export
    p, s = _open(slug)
    name = re.sub(r"[^A-Za-z0-9]+", "-", p.name).strip("-") or "project"
    return Response(case_export.workbook(p, s, include_srs=True, all_types=True),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}-test-cases.xlsx"'})


@app.get("/p/{slug}/results", response_class=HTMLResponse)
def results(request: Request, slug: str, run: str = ""):
    ctx = _ctx(request, slug, "results")
    s = ctx["store"]
    runs = s.all("SELECT * FROM runs ORDER BY started_at DESC LIMIT 20")
    run_id = run or (runs[0]["id"] if runs else "")
    rows = s.all("SELECT r.*, c.title, c.type, c.role, c.priority FROM results r LEFT JOIN cases c ON c.id = r.case_id "
                 "WHERE r.run_id=? ORDER BY (r.outcome='passed'), r.case_id", [run_id])
    return tpl.TemplateResponse(request, "results.html", {**ctx, "runs": runs, "run_id": run_id, "rows": rows})


@app.get("/p/{slug}/defects", response_class=HTMLResponse)
def defects(request: Request, slug: str):
    ctx = _ctx(request, slug, "defects")
    order = "CASE severity WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, seq"
    rows = ctx["store"].all(f"SELECT * FROM defects ORDER BY (status IN ('rejected','resolved')), {order}")
    for d in rows:
        for e in d["evidence"] or []:
            try:
                e["rel"] = Path(e["path"]).resolve().relative_to(ctx["project"].root).as_posix()
            except ValueError:
                e["rel"] = None
    return tpl.TemplateResponse(request, "defects.html", {**ctx, "rows": rows})


@app.post("/p/{slug}/defects")
async def defect_action(request: Request, slug: str):
    from agentqa.agents.triage import set_defect_status
    _, s = _open(slug)
    form = await request.form()
    ids = form.getlist("ids")
    action = form.get("action")
    if ids and action in ("confirmed", "rejected", "draft"):
        set_defect_status(s, ids, action, form.get("note") or "")
    return RedirectResponse(f"/p/{slug}/defects", status_code=303)


@app.get("/p/{slug}/defects.csv")
def defects_csv(slug: str):
    from agentqa.agents.triage import export_csv
    p, s = _open(slug)
    return FileResponse(export_csv(p, s, include_drafts=True), filename=f"{slug}-defects.csv", media_type="text/csv")


@app.get("/p/{slug}/defects-zoho.csv")
def defects_zoho_csv(slug: str):
    from agentqa.agents.triage import export_zoho_csv
    p, s = _open(slug)
    return FileResponse(export_zoho_csv(p, s, include_drafts=True), filename=f"{slug}-defects-zoho.csv",
                        media_type="text/csv")


def _moved(slug: str, page: str) -> RedirectResponse:
    """A page the new app replaced (M1.4 Phase C): the person goes there, and nothing is decided here, so every
    decision has who, why and the new app's checks (the templates go in Phase D)."""
    return RedirectResponse(f"/app/projects/{quote(slug, safe='')}/{page}", status_code=303)


@app.get("/p/{slug}/heals")
@app.post("/p/{slug}/heals/{hid}")
def heals(slug: str, hid: int | None = None):
    return _moved(slug, "heals")


@app.get("/p/{slug}/files/{rel:path}")
def project_file(slug: str, rel: str):
    p, _ = _open(slug)
    target = (p.root / rel).resolve()
    allowed = [p.reports_dir.resolve(), p.runs_dir.resolve(), p.tests_dir.resolve(), (p.root / "visual").resolve()]
    if not any(target.is_relative_to(a) for a in allowed) or not target.is_file():
        raise HTTPException(404)
    return FileResponse(target)


# ---------------------------------------------------------------------------
# APIs, visual review, imported tests, assistant
# ---------------------------------------------------------------------------

@app.get("/p/{slug}/apis", response_class=HTMLResponse)
def apis(request: Request, slug: str):
    ctx = _ctx(request, slug, "apis")
    s = ctx["store"]
    rows: dict[str, dict] = {}
    for e in s.all("SELECT * FROM endpoints ORDER BY pattern, role"):
        r = rows.setdefault(e["pattern"], {"pattern": e["pattern"], "method": e["method"], "callers": set(), "answers": {},
                                           "fields": [], "shape": "", "documented": False, "initiators": set(), "ms": []})
        if e["source"] == "traffic":
            r["callers"].add(e["role"])
            if e["initiator"]:
                r["initiators"].add(e["initiator"])
        r["answers"][e["role"]] = e["status"]
        r["documented"] = r["documented"] or bool(e["documented"])
        if e["keys"] and not r["fields"]:
            r["fields"], r["shape"] = e["keys"], e["shape"]
        if e["ms"]:
            r["ms"].append(e["ms"])
    run_id = s.get_meta("last_run")
    res = {x["case_id"]: x for x in s.all("SELECT * FROM results WHERE run_id=?", [run_id])} if run_id else {}
    tests: dict[str, list] = {}
    for c in s.all("SELECT * FROM cases WHERE type IN ('api_smoke','api_access','record_isolation') ORDER BY seq"):
        pat = (c["params"] or {}).get("pattern")
        tests.setdefault(pat, []).append({**c, "result": res.get(c["id"])})
    roles = list(ctx["project"].roles()) + ["anonymous"]
    return tpl.TemplateResponse(request, "apis.html", {**ctx, "rows": list(rows.values()), "tests": tests, "roles": roles})


@app.get("/p/{slug}/visual")
@app.post("/p/{slug}/visual-approve-all")
@app.post("/p/{slug}/visual/{key}")
def visual(slug: str, key: str | None = None):
    return _moved(slug, "visual")                      # the code moved to orchestrator/gates/visual.py


@app.get("/p/{slug}/imports", response_class=HTMLResponse)
def imports(request: Request, slug: str, msg: str = ""):
    ctx = _ctx(request, slug, "imports")
    p = ctx["project"]
    rows = ctx["store"].all("SELECT * FROM manual_cases ORDER BY (source_file='assistant'), id")
    sample = (p.root / "imports" / "manual_tests.xlsx").exists() or (ROOT / "demo" / "manual_tests.xlsx").exists()
    return tpl.TemplateResponse(request, "imports.html", {**ctx, "rows": rows, "msg": msg, "sample": sample})


@app.post("/p/{slug}/imports")
async def imports_upload(slug: str, file: UploadFile = File(None), sample: str = Form("")):
    from agentqa.agents import importer
    p, s = _open(slug)
    folder = p.root / "imports"
    folder.mkdir(exist_ok=True)
    if sample:
        src = folder / "manual_tests.xlsx"
        if not src.exists():
            shutil.copy(ROOT / "demo" / "manual_tests.xlsx", src)
        target = src
    else:
        if not file or not file.filename:
            raise HTTPException(400, "Choose an Excel or CSV file")
        name = Path(file.filename).name
        if Path(name).suffix.lower() not in (".xlsx", ".xlsm", ".csv"):
            raise HTTPException(400, "Upload an .xlsx or .csv file")
        target = folder / name
        target.write_bytes(await file.read())
    try:
        out = importer.import_file(p, s, target)
        msg = f"Imported {out['cases']} case(s) from {out['file']}: {out['ready']} fully automated, {out['review']} need review."
    except Exception as exc:  # noqa: BLE001
        msg = f"Could not import {target.name}: {exc}"
    from urllib.parse import quote
    return RedirectResponse(f"/p/{slug}/imports?msg={quote(msg)}", status_code=303)


@app.post("/p/{slug}/imports/action")
async def imports_action(request: Request, slug: str):
    from agentqa.agents import importer
    _, s = _open(slug)
    form = await request.form()
    ids = form.getlist("ids")
    action = form.get("action")
    if action == "approve_ready":
        ids = [m["id"] for m in s.all("SELECT id FROM manual_cases WHERE status='ready'")]
        action = "approved"
    if ids and action in ("approved", "rejected", "review"):
        importer.set_status(s, ids, action)
    return RedirectResponse(f"/p/{slug}/imports", status_code=303)


@app.get("/p/{slug}/assistant", response_class=HTMLResponse)
def assistant_page(request: Request, slug: str):
    from agentqa.agents.assistant import SUGGESTIONS
    ctx = _ctx(request, slug, "assistant")
    history = ctx["store"].all("SELECT * FROM chat ORDER BY id DESC LIMIT 40")[::-1]
    return tpl.TemplateResponse(request, "assistant.html", {**ctx, "history": history, "suggestions": SUGGESTIONS,
                                                           "model_on": str((ctx["project"].cfg.get("ai") or {}).get("mode") or "none") != "none"})


@app.post("/p/{slug}/assistant/ask")
async def assistant_ask(request: Request, slug: str):
    from agentqa.agents import assistant
    p, s = _open(slug)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - also accept a plain form post (curl, scripts)
        form = await request.form()
        body = {"question": form.get("question") or form.get("q") or ""}
    q = str((body or {}).get("question") or "").strip()
    if not q:
        raise HTTPException(400, "Ask a question")
    return assistant.answer(p, s, q)


@app.post("/p/{slug}/assistant/act")
async def assistant_act(request: Request, slug: str):
    p, s = _open(slug)
    body = await request.json()
    kind = body.get("kind")
    if kind == "run":
        only = [x for x in body.get("only") or [] if isinstance(x, str)]
        job = _spawn(p, s, ["run"] + (["--only", *only] if only else []), "run")
        return {"redirect": f"/p/{slug}/live?s=job-{job}-run"}
    if kind == "stage" and body.get("stage") in [x[0] for x in STAGE_INFO]:
        job = _spawn(p, s, [body["stage"]], body["stage"])
        return {"redirect": f"/p/{slug}/live?s=job-{job}-{body['stage']}"}
    raise HTTPException(400, "Unknown action")


# ---------------------------------------------------------------------------
# v0.4: pilot readiness, security scan, issue trackers, mock inbox
# ---------------------------------------------------------------------------

@app.get("/p/{slug}/readiness", response_class=HTMLResponse)
def readiness_page(request: Request, slug: str):
    ctx = _ctx(request, slug, "readiness")
    d = ctx["store"].get_meta("doctor")
    groups: dict[str, list] = {}
    for c in (d or {}).get("checks", []):
        groups.setdefault(_check_group(c["name"]), []).append(c)
    return tpl.TemplateResponse(request, "readiness.html", {**ctx, "d": d, "groups": groups})


def _check_group(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ("python", "disk", "browser", "parallel", "zap", "java", "model", "ollama")):
        return "This computer"
    if any(k in n for k in ("login", "captcha", "otp", "inbox", "role", "peer")):
        return "Logins and roles"
    if any(k in n for k in ("srs", "workflow", "data", "tracker", "jira", "azure")):
        return "Project setup"
    return "Test environment"


@app.post("/p/{slug}/readiness")
def readiness_run(slug: str, apply: str = Form("")):
    p, s = _open(slug)
    job = _spawn(p, s, ["doctor"] + (["--apply"] if apply else []), "doctor")
    return RedirectResponse(f"/p/{slug}/readiness?job={job}", status_code=303)


@app.get("/p/{slug}/security", response_class=HTMLResponse)
def security_page(request: Request, slug: str):
    from agentqa.agents import zapscan
    ctx = _ctx(request, slug, "security")
    s, p = ctx["store"], ctx["project"]
    meta = s.get_meta("zap")
    run_id = s.get_meta("zap_run")
    order = "CASE risk WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 WHEN 'Low' THEN 2 ELSE 3 END"
    alerts = s.all(f"SELECT alert, risk, plugin_id, cwe, sig, COUNT(*) n, MIN(url) url, MAX(solution) solution, "
                   f"MAX(description) description FROM zap_alerts WHERE run_id=? GROUP BY plugin_id, alert, risk "
                   f"ORDER BY {order}, n DESC", [run_id or "-"])
    defects = {d["signature"]: d for d in s.all("SELECT id, signature, status, severity FROM defects")}
    for a in alerts:
        a["defect"] = defects.get(a["sig"])
        a["path"] = (a["url"] or "").replace(p.base_url, "") or "/"
    return tpl.TemplateResponse(request, "security.html", {**ctx, "meta": meta, "alerts": alerts, "status": zapscan.status(p.cfg),
                                                          "zcfg": p.cfg.get("zap") or {}})


@app.get("/p/{slug}/integrations", response_class=HTMLResponse)
def integrations_page(request: Request, slug: str, test: str = ""):
    from agentqa.integrations import trackers
    ctx = _ctx(request, slug, "integrations")
    s, p = ctx["store"], ctx["project"]
    systems = trackers.configured(p.cfg)
    tests = trackers.test_connection(p.cfg) if test else []
    linked = s.all("SELECT id, title, severity, status, external_system, external_key, external_url, external_status "
                   "FROM defects WHERE external_key IS NOT NULL AND external_key != '' ORDER BY seq")
    log_rows = s.all("SELECT * FROM sync_log ORDER BY id DESC LIMIT 60")
    ready = s.scalar("SELECT COUNT(*) FROM defects WHERE status='confirmed' AND (external_key IS NULL OR external_key='')") or 0
    return tpl.TemplateResponse(request, "integrations.html", {
        **ctx, "systems": systems, "tests": tests, "linked": linked, "log_rows": log_rows, "ready": ready,
        "last": s.get_meta("tracker_sync"), "tcfg": trackers.trackers_cfg(p.cfg)})


@app.post("/p/{slug}/integrations/sync")
def integrations_sync(slug: str):
    p, s = _open(slug)
    job = _spawn(p, s, ["sync"], "sync")
    return RedirectResponse(f"/p/{slug}/integrations?job={job}", status_code=303)


@app.get("/p/{slug}/inbox", response_class=HTMLResponse)
def inbox_page(request: Request, slug: str):
    from agentqa import inbox
    ctx = _ctx(request, slug, "inbox")
    p = ctx["project"]
    st = inbox.settings(p.cfg)
    url = inbox.client_url(p.cfg)
    running = inbox.InboxClient(url).alive()
    msgs = []
    db = p.state / "inbox.db"
    if running:
        try:
            msgs = inbox.InboxClient(url).messages()
        except Exception:  # noqa: BLE001
            msgs = []
    if not msgs and db.exists():
        msgs = inbox.InboxStore(db).list(limit=100)
    for m in msgs:
        m["otp"] = inbox.extract_otp(m.get("body") or "", (p.cfg.get("login", {}).get("otp") or {}).get("pattern"))
    otp_roles = [r for r, v in p.roles().items() if v.get("mobile") or v.get("email")]
    return tpl.TemplateResponse(request, "inbox.html", {**ctx, "msgs": msgs, "st": st, "url": url, "inbox_running": running,
                                                       "otp_roles": otp_roles, "otp_cfg": p.cfg.get("login", {}).get("otp") or {}})


@app.post("/p/{slug}/inbox/start")
def inbox_start(slug: str):
    from agentqa import inbox
    p, _ = _open(slug)
    inbox.ensure(p)
    return RedirectResponse(f"/p/{slug}/inbox", status_code=303)


@app.post("/p/{slug}/inbox/clear")
def inbox_clear(slug: str):
    from agentqa import inbox
    p, _ = _open(slug)
    if (p.state / "inbox.db").exists():
        inbox.InboxStore(p.state / "inbox.db").clear()
    return RedirectResponse(f"/p/{slug}/inbox", status_code=303)


# ---------------------------------------------------------------------------
# v0.5: test data vault, ask-the-tester channel
# ---------------------------------------------------------------------------

@app.get("/p/{slug}/testdata", response_class=HTMLResponse)
def testdata_page(request: Request, slug: str, msg: str = "", edit: str = "", edit_app: str = ""):
    from agentqa import login_flow
    from agentqa.vault import METHODS, OTP_SOURCES, mask
    ctx = _ctx(request, slug, "testdata")
    p, s = ctx["project"], ctx["store"]
    v = p.vault
    vs = v.summary() if v.path.exists() else {}
    last_auth = {}
    for a in s.all("SELECT * FROM auth_log ORDER BY id DESC LIMIT 200"):
        last_auth.setdefault(a["role"], a)
    rows = []
    for role in list(p.roles()) + p.peers():
        acc = p.account(role)
        steps = v.login_steps(role) if v.path.exists() else []
        extra = login_flow._extras(acc)
        st = account_status(p, role)
        sess = p.auth_file(role).exists()
        rows.append({"role": role, "peer": role.endswith("__peer"), "owner": role.replace("__peer", ""),
                     "login_option": acc.get("login_option") or "",
                     "method": acc.get("method") or st["method"], "app": p.app_of(role),
                     "extra": "\n".join(f"{k} = {v}" for k, v in extra.items()),
                     "username": acc.get("username") or "", "mobile": acc.get("mobile") or "",
                     "email": acc.get("email") or "", "otp_source": st["otp_source"],
                     "has_password": bool(acc.get("password") or os.environ.get(acc.get("password_env") or "-")),
                     "has_fixed_otp": bool(acc.get("otp_fixed")), "has_totp": bool(acc.get("totp_secret")),
                     "in_vault": role in vs, "aliases": acc.get("aliases") or "",
                     "steps": login_flow.describe(steps), "ready": st["ready"], "missing": st["missing"],
                     "last": last_auth.get(role), "session": sess,
                     "nav_hints": len(v.nav_hints(role)) if v.path.exists() and not role.endswith("__peer") else 0})
    secrets = {k: mask(val) for k, val in ((v.load()["secrets"] if v.path.exists() else {}) or {}).items()}
    editing = next((r for r in rows if r["role"] == edit), None)
    auth = s.all("SELECT * FROM auth_log ORDER BY id DESC LIMIT 40")
    ready_n = sum(1 for r in rows if r["ready"] and not r["peer"])
    return tpl.TemplateResponse(request, "testdata.html", {
        **ctx, "rows": rows, "methods": METHODS, "otp_sources": OTP_SOURCES, "datasets": v.datasets() if v.path.exists() else {},
        "secrets": secrets, "msg": msg, "editing": editing, "auth": auth, "apps": p.applications(),
        "edit_app": edit_app, "envs": ["Development", "Test / QA", "UAT", "Staging", "Production"],
        "ready_n": ready_n, "roles_n": sum(1 for r in rows if not r["peer"]), "add": request.query_params.get("add")})


@app.post("/p/{slug}/testdata/account")
async def testdata_account(request: Request, slug: str):
    import re as _re
    p, _ = _open(slug)
    f = await request.form()
    role = _re.sub(r"[^a-z0-9_]", "_", str(f.get("role") or "").strip().lower()).strip("_")
    if not role:
        raise HTTPException(400, "Give the role a name")
    if f.get("peer_of"):
        role = f"{f.get('peer_of')}__peer"
    values = {k: str(f.get(k) or "").strip() for k in ("login_option", "method", "username", "mobile", "email", "password",
                                                       "otp_source", "otp_fixed", "totp_secret", "aliases", "app", "extra")}
    # keep only what this way of logging in needs, so a changed method never leaves stale details behind
    m = values["method"] or "password"
    if m == "mobile_otp":
        values["username"] = values["password"] = values["email"] = ""
    elif m == "email_otp":
        values["password"] = values["mobile"] = ""
    elif m == "password":
        values["mobile"] = values["mobile"] if values.get("mobile") and f.get("keep_mobile") else ""
        values["otp_source"] = values["otp_fixed"] = values["totp_secret"] = ""
    clear = [k for k in ("otp_fixed", "totp_secret") if values.get("otp_source") != {"otp_fixed": "fixed", "totp_secret": "totp"}[k]]
    if m in ("mobile_otp", "email_otp"):
        clear.append("password")
    p.vault.set_account(role, values)            # an empty password box keeps the stored one
    acc = p.vault.accounts().get(role) or {}
    for k in clear:                              # ...unless this way of logging in has no such thing
        acc.pop(k, None)
    p.vault.save()
    if f.get("relearn"):
        p.vault.set_login_steps(role, None)
    from urllib.parse import quote
    return RedirectResponse(f"/p/{slug}/testdata?msg={quote('Saved the ' + role.replace('__peer', ' second') + ' account')}", status_code=303)


@app.post("/p/{slug}/testdata/app")
async def testdata_app(request: Request, slug: str):
    """Add or edit an application (portal) under test; written to project.yaml (no secrets in it)."""
    import re as _re
    from agentqa import yamledit
    p, _ = _open(slug)
    f = await request.form()
    aid = _re.sub(r"[^a-z0-9_]", "_", str(f.get("id") or "").strip().lower()).strip("_")
    url = str(f.get("base_url") or "").strip().rstrip("/")
    if not aid or not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Give the application an id and a full http(s) URL")
    if _proj.address_problem(url):                                  # user:password@ in the address (M1.4 review)
        raise HTTPException(422, _proj.address_problem(url))
    raw = dict(p.cfg.get("applications") or {})
    if not raw:     # the project so far had one site: keep it as the primary application
        raw = {"main": {"name": p.name, "base_url": p.base_url}}
    cur = dict(raw.get(aid) or {})
    split = lambda k: [x.strip() for x in str(f.get(k) or "").split(",") if x.strip()]  # noqa: E731
    cur.update({"name": str(f.get("name") or aid).strip(), "base_url": url, "environment": str(f.get("environment") or ""),
                "auth": str(f.get("auth") or ""), "module": str(f.get("module") or ""),
                "description": str(f.get("description") or ""), "priority": int(f.get("priority") or len(raw) + 1),
                "scope": {"include": split("include"), "exclude": split("exclude")}, "srs": split("srs")})
    login = {k: str(f.get("login_" + k) or "").strip() for k in ("start", "url")}
    if any(login.values()):
        cur["login"] = {k: v for k, v in login.items() if v}
    raw[aid] = cur
    yamledit.replace_top_block(p.config_path, "applications", yaml.safe_dump({"applications": raw}, sort_keys=False))
    if aid == next(iter(raw)) and url != p.base_url:
        yamledit.replace_top_block(p.config_path, "base_url", yaml.safe_dump({"base_url": url}, sort_keys=False))
    return RedirectResponse(f"/p/{slug}/testdata?msg={quote('Saved ' + cur['name'])}#apps", status_code=303)


@app.post("/p/{slug}/testdata/account/{role}/{action}")
def testdata_account_action(slug: str, role: str, action: str):
    p, _ = _open(slug)
    if action == "delete":
        p.vault.remove_account(role)
    elif action == "relearn":
        p.vault.set_login_steps(role, None)
    elif action == "teach":
        # the person logs in once in AgentQA's browser (from the box on every page, or the window when it can open);
        # AgentQA records the path and keeps the details they type
        _, s = _open(slug)
        _spawn(p, s, ["teach-login", "--role", role], f"teach-{role}", headed=True)
        return RedirectResponse(f"/p/{slug}/testdata?msg={quote('Show AgentQA how to log in as ' + role + ': the box opens in a moment')}",
                                status_code=303)
    return RedirectResponse(f"/p/{slug}/testdata", status_code=303)


@app.post("/p/{slug}/testdata/dataset")
async def testdata_dataset(request: Request, slug: str):
    p, _ = _open(slug)
    f = await request.form()
    name = str(f.get("name") or "").strip()
    values = [x.strip() for x in str(f.get("values") or "").splitlines() if x.strip()]
    if name:
        p.vault.set_dataset(name, values if not f.get("delete") else None)
    return RedirectResponse(f"/p/{slug}/testdata#datasets", status_code=303)


@app.post("/p/{slug}/testdata/secret")
async def testdata_secret(request: Request, slug: str):
    p, _ = _open(slug)
    f = await request.form()
    name = str(f.get("name") or "GOOGLE_API_KEY").strip()
    p.vault.set_secret(name, None if f.get("delete") else (str(f.get("value") or "").strip() or None))
    return RedirectResponse(f"/p/{slug}/testdata#secrets", status_code=303)


# ---------------------------------------------------------------------------
# AI providers (installation-wide keys, failover policy, health and audit log)
# ---------------------------------------------------------------------------

def _ai_ctx():
    from agentqa.ai import gateway
    from agentqa.ai.providers import CATALOG, KINDS
    gw = gateway()
    return gw, CATALOG, KINDS


@app.get("/p/{slug}/ai", response_class=HTMLResponse)
def ai_page(request: Request, slug: str, edit: str = "", msg: str = ""):
    import time as _t
    gw, catalog, kinds = _ai_ctx()
    ctx = _ctx(request, slug, "ai")
    try:
        keys = gw.store.public_keys()
    except RuntimeError as exc:          # the settings were encrypted for another Windows account
        keys, msg = [], str(exc)
    now = _t.time()
    for k in keys:
        st = k["state"] or {}
        cool = (st.get("cooldown_until") or 0) - now
        k["cool_s"] = int(cool) if cool > 0 else 0
        dead = st.get("state") in ("invalid_key", "billing", "model")
        k["usable"] = k.get("status", "active") == "active" and not dead and not k["cool_s"]
    pol = gw.store.policy()
    counts = gw.store.counts()
    summary = {"keys": len(keys), "active": sum(1 for k in keys if k.get("status", "active") == "active"),
               "usable": sum(1 for k in keys if k["usable"]), "cooling": sum(1 for k in keys if k["cool_s"]),
               "dead": sum(1 for k in keys if (k["state"] or {}).get("state") in ("invalid_key", "billing", "model")),
               "ok_today": counts.get("ok", 0), "switches_today": counts.get("switched", 0),
               "failures_today": sum(v for o, v in counts.items() if o in kinds and o != "ok")}
    editing = next((k for k in keys if k["id"] == edit), None)
    return tpl.TemplateResponse(request, "ai.html", {
        **ctx, "keys": keys, "policy": pol, "catalog": catalog, "kinds": kinds, "events": gw.store.events(80),
        "summary": summary, "editing": editing, "msg": msg, "home": str(gw.store.home),
        "project_on": str((ctx["project"].cfg.get("ai") or {}).get("mode") or "none") != "none",
        "project_mode": str((ctx["project"].cfg.get("ai") or {}).get("mode") or "none")})


@app.post("/p/{slug}/ai/key")
async def ai_key(request: Request, slug: str):
    gw, catalog, _ = _ai_ctx()
    f = await request.form()
    provider = str(f.get("provider") or "")
    if provider not in catalog:
        raise HTTPException(400, "Unknown provider")
    vals = {k: str(f.get(k) or "").strip() for k in ("id", "label", "key", "base_url", "model", "fallback_model",
                                                       "deployment", "api_version")}
    vals = {k: v for k, v in vals.items() if v or k in ("key", "fallback_model", "base_url")}
    if vals.get("base_url"):
        from agentqa.orchestrator import preflight
        try:
            vals["base_url"] = preflight.check_base_url(vals["base_url"])
        except ValueError as exc:
            raise HTTPException(400, f"Address: {exc}") from exc
    vals.update(provider=provider, priority=int(f.get("priority") or 10),
                status="disabled" if f.get("disabled") else "active")
    vals["label"] = vals.get("label") or f"{catalog[provider]['name']} key"
    vals["model"] = vals.get("model") or "auto"
    kid = gw.store.upsert_key(vals)
    msg = "Saved."
    if f.get("test"):
        res = gw.test(kid)
        msg = ("Saved and tested: " if res["ok"] else "Saved, but the test failed: ") + res["detail"]
    return RedirectResponse(f"/p/{slug}/ai?msg={quote(msg)}#keys", status_code=303)


@app.post("/p/{slug}/ai/key/{kid}/{action}")
def ai_key_action(slug: str, kid: str, action: str):
    gw, _, _ = _ai_ctx()
    msg = ""
    if action == "test":
        res = gw.test(kid)
        msg = ("Connection OK: " if res["ok"] else "Test failed: ") + res["detail"]
    elif action in ("enable", "disable"):
        gw.store.upsert_key({"id": kid, "status": "active" if action == "enable" else "disabled"})
    elif action == "reset":
        gw.store.reset_state(kid)
    elif action == "delete":
        gw.store.delete_key(kid)
    else:
        raise HTTPException(404)
    return RedirectResponse(f"/p/{slug}/ai?msg={quote(msg)}#keys", status_code=303)


@app.post("/p/{slug}/ai/test-all")
def ai_test_all(slug: str):
    gw, _, _ = _ai_ctx()
    ok = bad = 0
    for k in gw.store.keys():
        if k.get("status", "active") == "active":
            res = gw.test(k["id"])
            ok, bad = ok + bool(res["ok"]), bad + (not res["ok"])
    return RedirectResponse(f"/p/{slug}/ai?msg={quote(f'{ok} key(s) answered, {bad} failed.')}#keys", status_code=303)


@app.post("/p/{slug}/ai/policy")
async def ai_policy(request: Request, slug: str):
    gw, catalog, _ = _ai_ctx()
    f = await request.form()
    order = [x.strip() for x in str(f.get("order") or "").replace("\n", ",").split(",") if x.strip() in catalog]
    order += [p for p in gw.store.policy()["order"] if p not in order]
    num = lambda k, d: float(f.get(k) or d)  # noqa: E731
    gw.store.set_policy({"order": order, "provider_fallback": bool(f.get("provider_fallback")),
                         "attempts_per_key": int(num("attempts_per_key", 2)), "timeout_s": num("timeout_s", 60),
                         "backoff_s": num("backoff_s", 1), "redact": bool(f.get("redact")),
                         "cooldown_s": {k: num("cd_" + k, v) for k, v in gw.store.policy()["cooldown_s"].items()}})
    return RedirectResponse(f"/p/{slug}/ai?msg=Policy+saved.#policy", status_code=303)


@app.post("/p/{slug}/ai/project")
async def ai_project(request: Request, slug: str):
    """A toggle between No AI and the project's last non-none mode (the new AI page chooses among all four)."""
    from agentqa.ai import settings as ai_settings
    p, _ = _open(slug)
    f = await request.form()
    block = {k: v for k, v in (p.cfg.get("ai") or {}).items() if k != "migrated_from"}
    current = str(block.get("mode") or "none")
    if f.get("enabled"):
        block["mode"] = str(block.get("last_mode") or "local")
    else:
        block["mode"] = "none"
        if current != "none":
            block["last_mode"] = current
    ai_settings.save_ai(p.config_path, block)
    return RedirectResponse(f"/p/{slug}/ai#project", status_code=303)


# ---- the old help box (M1.4 Phase C): still on the pages not yet moved, it goes through the new app's service, so
# it keeps the same rules (caps, who, the Viewer rule, one answer); Phase D removes it with those pages.

def _user(request: Request):
    return getattr(request.state, "agentqa_user", None)          # set by the API's guard in front of this app


def _who(request: Request) -> str:
    from agentqa.orchestrator.gates import changelog
    user = _user(request)
    return changelog.who(user) if user else "dashboard"


def _may_drive(request: Request) -> bool:
    from agentqa.api.auth import WRITE_ROLES
    user = _user(request)
    return user is None or user.role in WRITE_ROLES          # None: this app on its own (its own tests, a tool)


@contextmanager
def _gate_store(slug: str, aid: int):
    """The project and store for one help-box request, closed afterwards; refusals answer as the API does."""
    from agentqa.orchestrator.gates import GateError
    if not 0 < aid <= MAX_ROW_ID:
        raise HTTPException(404, "No such question")
    try:
        with _proj.project_store(slug) as pair:
            yield pair
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except GateError as exc:
        raise HTTPException(exc.status, exc.message) from exc


async def _body(request: Request, parse):
    try:
        return parse(await request.json())
    except ValueError as exc:                              # bad JSON, or not what the new app's schema allows
        raise HTTPException(422, "That is not something the help box can send") from exc


@app.get("/p/{slug}/assist/pending")
def assist_pending(request: Request, slug: str):
    """The new app's list (capped, never an answer) in the old box's shape; a Viewer gets nothing (the old box has
    no watching mode: the new app shows a Viewer who is waiting)."""
    from agentqa.orchestrator.gates import helpbox
    if not _may_drive(request):
        return []
    with _gate_store(slug, 1) as (p, _):
        items = helpbox.pending(p, True)["items"]
    base = f"/api/v1/projects/{quote(slug, safe='')}/assist"
    return [{**q, "shot": f"{base}/{q['id']}/shot?v={q['shot_v']}" if q["has_shot"] else None} for q in items]


@app.post("/p/{slug}/assist/{aid}/cmd")
async def assist_cmd(request: Request, slug: str, aid: int):
    """Take-over: one action on the agent's browser (click on the screenshot, type, press a key, go back)."""
    from pydantic import TypeAdapter

    from agentqa.api.schemas_review import CommandIn
    from agentqa.orchestrator.gates import helpbox
    cmd = await _body(request, lambda raw: TypeAdapter(CommandIn).validate_python(raw).model_dump())
    with _gate_store(slug, aid) as (p, s):
        return {"ok": True, **helpbox.command(p, s, aid, cmd, _who(request))}


@app.post("/p/{slug}/pause")
def pause_agents(request: Request, slug: str):
    from agentqa.orchestrator.gates import helpbox
    with _gate_store(slug, 1) as (p, s):
        helpbox.pause(p, s, _who(request))
    return {"ok": True, "paused": True}


@app.post("/p/{slug}/resume")
def resume_agents(request: Request, slug: str):
    from agentqa.orchestrator.gates import helpbox
    with _gate_store(slug, 1) as (p, s):
        helpbox.resume(p, s, _who(request))
    return {"ok": True, "paused": False}


@app.get("/p/{slug}/paused")
def paused_state(slug: str):
    from agentqa import assist
    p, _ = _open(slug)
    return {"paused": assist.paused(p)}


@app.get("/p/{slug}/assist/{aid}/shot")
def assist_shot(request: Request, slug: str, aid: int):
    from agentqa.orchestrator.gates import helpbox
    if not _may_drive(request):
        raise HTTPException(403, "Only the owner or a tester sees the agent's screen")
    with _gate_store(slug, aid) as (p, _):
        found = helpbox.shot(p, aid)
    return FileResponse(found.path, media_type=found.media_type, headers={"Cache-Control": "no-store"})


@app.post("/p/{slug}/assist/{aid}")
async def assist_answer(request: Request, slug: str, aid: int):
    from agentqa.api.schemas_review import AssistAnswerIn
    from agentqa.orchestrator.gates import helpbox
    ans = await _body(request, lambda raw: AssistAnswerIn.model_validate(raw).answer())
    with _gate_store(slug, aid) as (_, s):
        helpbox.answer(s, aid, ans, _who(request))
    return {"ok": True}
