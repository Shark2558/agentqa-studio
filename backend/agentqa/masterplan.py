"""Master plan: every activity from setup to report, what is done, what is running, what is waiting for a person,
and the single next thing to do.

The dashboard shows the whole list on the Master plan page and the next action in a banner on every page, so a
tester is told what to do, in order, instead of guessing which button comes next.

Statuses: done · running · you (waiting for a person) · next (ready to start) · pending (not yet reachable) ·
skipped (not applicable) · optional.
"""
from __future__ import annotations

from agentqa.config import Project
from agentqa.store import Store

PHASES = [("setup", "Set up"), ("understand", "Understand"), ("test", "Test"), ("report", "Report and share")]


def _stage_rows(store: Store) -> dict[str, dict]:
    """Latest stage_runs row per stage (the newest pipeline first, then single runs)."""
    out: dict[str, dict] = {}
    for r in store.all("SELECT * FROM stage_runs ORDER BY id DESC LIMIT 400"):
        out.setdefault(r["stage"], r)
    return out


def _done_at(r: dict | None) -> str:
    return ((r or {}).get("finished_at") or "")[:16].replace("T", " ")


def compute(project: Project, store: Store, running: dict | None = None) -> dict:
    """{"items": [...], "next": item|None, "progress": {"done", "total"}, "phase_counts": {...}}"""
    from agentqa.login_flow import account_status  # the same readiness rule the Test data page uses
    p, s = project, store
    slug_base = f"/p/{p.root.name}"
    roles = list(p.roles())
    accounts = {r: account_status(p, r) for r in roles}
    srs_files = [f for f in p.srs_dir.iterdir() if f.is_file()] if p.srs_dir.exists() else []
    vault_ok = p.vault.path.exists()
    learnt = {r: bool(vault_ok and (p.vault.login_steps(r) or p.auth_file(r).exists())) for r in roles}
    st = _stage_rows(s)
    active = (running or {}).get("stage")
    reqs = s.scalar("SELECT COUNT(*) FROM requirements") or 0
    screens = s.scalar("SELECT COUNT(DISTINCT path) FROM screens") or 0
    questions = s.scalar("SELECT COUNT(*) FROM questions WHERE status='open'") or 0
    answered = s.scalar("SELECT COUNT(*) FROM questions WHERE status!='open'") or 0
    rules_set = s.scalar("SELECT COUNT(*) FROM rules WHERE status IS NOT NULL") or 0
    writer = s.get_meta("writer")
    cases = s.scalar("SELECT COUNT(*) FROM cases") or 0
    proposed = s.scalar("SELECT COUNT(*) FROM cases WHERE status='proposed'") or 0
    plan = s.one("SELECT * FROM plan WHERE id=1")
    tests_written = p.tests_dir.exists() and any(p.tests_dir.glob("test_*.py"))
    run = s.one("SELECT * FROM runs WHERE status='done' ORDER BY started_at DESC LIMIT 1")
    expl = s.get_meta("exploratory")
    zap = s.get_meta("zap")
    triage = s.get_meta("triage")
    drafts = s.scalar("SELECT COUNT(*) FROM defects WHERE status='draft'") or 0
    confirmed = s.scalar("SELECT COUNT(*) FROM defects WHERE status IN ('confirmed','exported')") or 0
    defects_open = s.scalar("SELECT COUNT(*) FROM defects WHERE status NOT IN ('rejected','resolved')") or 0
    heals = s.scalar("SELECT COUNT(*) FROM heals WHERE status='proposed'") or 0
    heals_any = s.scalar("SELECT COUNT(*) FROM heals") or 0
    report_ok = (p.reports_dir / "report.html").exists()
    exported = s.scalar("SELECT COUNT(*) FROM defects WHERE status='exported'") or 0
    zoho_done = (p.reports_dir / "defects-zoho.csv").exists()
    prod = any(p.is_production(a) for a in p.applications())

    items: list[dict] = []

    def add(key, phase, name, status, detail="", action=None, who="AgentQA", when=""):
        items.append({"key": key, "phase": phase, "name": name, "status": status, "detail": detail, "action": action,
                      "who": who, "when": when})

    # ---- Set up (a person) ------------------------------------------------------------------------
    ready = [r for r in roles if accounts[r]["ready"]]
    missing = [f"{r} ({', '.join(accounts[r]['missing'])})" for r in roles if not accounts[r]["ready"]]
    add("accounts", "setup", "Add one test account per role",
        "done" if roles and not missing else "you",
        (f"{len(ready)} of {len(roles)} active" + (f"; add: {'; '.join(missing[:3])}" if missing else "")) if roles
        else "No accounts yet: add the citizen, clerk, officer... accounts AgentQA will log in with",
        {"label": "Open Test data", "href": f"{slug_base}/testdata"}, who="You")
    envs_unset = [a["name"] for a in p.applications().values() if not a.get("environment")]
    add("environment", "setup", "Say whether each portal is a test or production environment",
        "done" if not envs_unset else "you",
        ("Production portals get read-only checks only" if not envs_unset else f"Not set for: {', '.join(envs_unset)}"),
        {"label": "Set environment", "href": f"{slug_base}/testdata#apps"}, who="You")
    add("srs", "setup", "Upload the requirement documents (SRS)",
        "done" if srs_files else "you",
        f"{len(srs_files)} file(s)" if srs_files else "Put the SRS (.docx, .pdf, .xlsx, .md...) in the srs folder or upload it",
        {"label": "Requirements page", "href": f"{slug_base}/srs"}, who="You")
    not_learnt = [r for r in roles if not learnt[r]]
    add("logins", "setup", "Let AgentQA learn each login (or show it the way)",
        "done" if roles and not not_learnt else ("pending" if missing or not roles else "next"),
        ("Learnt for every role" if roles and not not_learnt else
         f"Not yet for: {', '.join(not_learnt)}. The Explorer learns it at the first login and asks you if stuck; "
         "or press 'Show how to log in' on Test data") if roles else "Add accounts first",
        {"label": "Test the logins", "href": f"{slug_base}/readiness"}, who="You + AgentQA")

    # ---- Understand -----------------------------------------------------------------------------------
    def stage(key, phase, name, done_cond, detail_done, detail_todo, gate_before=None):
        r = st.get(key)
        if active == key:
            status, detail = "running", "Running now: watch it in Live View"
        elif done_cond:
            status, detail = "done", detail_done
        elif gate_before and gate_before():
            status, detail = "pending", detail_todo
        elif r and r.get("status") == "failed":
            status, detail = "failed", f"Failed: {str(r.get('error') or '')[:140]}"
        else:
            status, detail = "next", detail_todo
        add(key, phase, name, status, detail, {"label": "Run this step", "href": f"{slug_base}/run/{key}", "post": True}
            if status in ("next", "failed") else {"label": "Watch in Live View", "href": f"{slug_base}/live"} if status == "running"
            else None, when=_done_at(r) if status == "done" else "")

    stage("analyze", "understand", "Requirement Analyst reads the SRS", reqs > 0,
          f"{reqs} requirements, {s.scalar('SELECT COUNT(*) FROM rules') or 0} rules",
          "Reads the documents into numbered requirements and testable rules", gate_before=lambda: not srs_files)
    stage("explore", "understand", "Explorer logs in as every role and maps the portal", screens > 0,
          f"{screens} screens across {s.scalar('SELECT COUNT(DISTINCT role) FROM screens') or 0} roles",
          "Logs in as each role (English first), maps every screen, form, link and API",
          gate_before=lambda: bool(missing) or not roles)
    stage("reconcile", "understand", "Reconciler compares the SRS with the portal", rules_set > 0,
          f"{rules_set} rules settled, {questions} open question(s)",
          "Finds where the SRS and the live portal disagree", gate_before=lambda: not (reqs and screens))
    add("gate1", "understand", "Gate 1: answer the SRS questions",
        "you" if questions else ("done" if answered or rules_set else "pending"),
        (f"{questions} question(s) wait; the rules behind them stay untested until you answer" if questions
         else (f"{answered} answered" if answered else "Nothing to answer yet")),
        {"label": "Answer questions", "href": f"{slug_base}/questions"} if questions else None, who="You")
    stage("write", "understand", "Requirement Writer rewrites each requirement clearly", bool(writer),
          f"{(writer or {}).get('requirements', 0)} rewritten ({(writer or {}).get('by_model', 0)} by the model)",
          "Turns each requirement into a statement, steps and acceptance criteria (model when set up, else rules)",
          gate_before=lambda: not reqs)

    # ---- Test -----------------------------------------------------------------------------------------
    stage("design", "test", "Planner + Designer writes the test cases", cases > 0,
          f"{cases} test cases ({proposed} awaiting approval)" if proposed else f"{cases} test cases",
          "Builds the risk-ranked plan and every test case with its expected result and source",
          gate_before=lambda: not (reqs and screens))
    add("gate2", "test", "Gate 2: approve the test plan",
        "done" if plan and plan.get("approved") else ("you" if cases else "pending"),
        (f"Approved {str(plan.get('approved_at') or '')[:16].replace('T', ' ')}" if plan and plan.get("approved")
         else (f"{proposed} case(s) wait for your approval; this is the only gate that stops the pipeline" if cases
               else "Design the test cases first")),
        {"label": "Review the plan", "href": f"{slug_base}/plan"} if cases and not (plan and plan.get("approved")) else None,
        who="You")
    stage("generate", "test", "Script Generator writes the test code", bool(tests_written),
          f"{len(list(p.tests_dir.glob('test_*.py'))) if tests_written else 0} test files",
          "Writes readable pytest + Playwright code for every approved case",
          gate_before=lambda: not (plan and plan.get("approved")))
    stage("run", "test", "Executor runs the tests", bool(run),
          f"{run['passed']} of {run['total']} passed" + (f", {run.get('blocked') or 0} blocked" if run and run.get("blocked") else "")
          if run else "", "Runs the suite in parallel browsers and keeps evidence for every test",
          gate_before=lambda: not tests_written)
    stage("exploratory", "test", "Exploratory Tester wanders like a curious user", bool(expl),
          f"{(expl or {}).get('steps', 0)} steps, {(expl or {}).get('findings', 0)} findings",
          "Odd inputs, other roles' addresses, JS errors, security headers" + (" (read-only on production)" if prod else ""),
          gate_before=lambda: not screens)
    zap_state = "skipped" if zap and "skipped" in (zap or {}) else ("done" if zap else None)
    r_sec = st.get("security")
    add("security", "test", "Security Scanner (OWASP ZAP)",
        "running" if active == "security" else (zap_state or ("pending" if not screens else "optional")),
        (f"{zap.get('alerts', 0)} alerts, {zap.get('findings', 0)} for triage" if zap and "alerts" in zap
         else "Skipped: ZAP is not installed (optional; install it to scan)" if zap_state == "skipped"
         else "Passive scan of every screen as each role; active scans only on test environments"),
        {"label": "Run this step", "href": f"{slug_base}/run/security", "post": True} if screens and not zap else None,
        when=_done_at(r_sec) if zap else "")
    stage("triage", "test", "Triage groups failures into defects", bool(triage),
          f"{defects_open} open defect(s), {drafts} draft(s) to confirm",
          "One defect per root cause, merged across scripted, exploratory and visual tests", gate_before=lambda: not run)
    add("gate3", "report", "Gate 3: confirm the real defects",
        "you" if drafts else ("done" if confirmed or (triage and not defects_open) else "pending"),
        (f"{drafts} draft(s) wait for your confirmation; only confirmed defects are exported" if drafts
         else (f"{confirmed} confirmed" if confirmed else ("No defects found" if triage else "Run Triage first"))),
        {"label": "Review defects", "href": f"{slug_base}/defects"} if drafts else None, who="You")
    add("heal", "report", "Healer proposes fixes for tests broken by UI changes",
        "you" if heals else ("done" if heals_any or (run and triage) else "pending"),
        (f"{heals} proposal(s) wait for your review" if heals else ("Nothing to heal" if (run and triage) else "After a run")),
        {"label": "Review proposals", "href": f"{slug_base}/heals"} if heals else None, who="You" if heals else "AgentQA")
    stage("report", "report", "Reporter writes the HTML report and traceability matrix", report_ok,
          "Report ready", "HTML report, RTM and release readiness score", gate_before=lambda: not run)
    add("share_cases", "report", "Download the test cases (Excel, standard template)",
        "optional" if not cases else "next" if report_ok else "pending",
        f"{cases} case(s) with their last result" if cases else "After the test cases are designed",
        {"label": "Download Excel", "href": f"{slug_base}/testcases.xlsx"} if cases else None, who="You")
    add("share_defects", "report", "Export the defects to Zoho (or Jira / Azure DevOps)",
        "done" if (exported or zoho_done) else ("next" if confirmed else ("optional" if triage else "pending")),
        (f"{exported} synced" if exported else "Zoho file written" if zoho_done else
         f"{confirmed} confirmed defect(s) ready" if confirmed else "Confirm defects first"),
        {"label": "Export for Zoho", "href": f"{slug_base}/defects-zoho.csv"} if (confirmed or drafts) else None, who="You")

    # ---- the next thing to do: a person's turn first, then the first step ready to run -----------------
    nxt = None
    if running:
        nxt = {"key": "running", "name": f"{running['stage']} is running", "status": "running",
               "detail": "Watch it in Live View; AgentQA asks you in a box if it needs an OTP or a hint",
               "action": {"label": "Open Live View", "href": f"{slug_base}/live"}, "who": "AgentQA", "phase": ""}
    else:
        order = {"you": 0, "failed": 1, "next": 2}
        cands = [i for i in items if i["status"] in order]
        if cands:
            nxt = sorted(cands, key=lambda i: (order[i["status"]], items.index(i)))[0]
    done = sum(1 for i in items if i["status"] in ("done", "skipped"))
    counted = [i for i in items if i["status"] != "optional"]
    phase_counts = {k: {"done": sum(1 for i in items if i["phase"] == k and i["status"] in ("done", "skipped")),
                        "total": sum(1 for i in items if i["phase"] == k and i["status"] != "optional")} for k, _ in PHASES}
    return {"steps": items, "items": items, "next": nxt, "progress": {"done": done, "total": len(counted)}, "phase_counts": phase_counts,
            "phases": PHASES, "phase_names": dict(PHASES)}
