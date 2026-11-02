"""agentqa command line. Run `python -m agentqa --help`."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

from agentqa import live
from agentqa.config import Project, init_project
from agentqa.store import Store, now
from agentqa.util import log

STAGES = ["analyze", "explore", "reconcile", "write", "design", "generate", "run", "exploratory", "security", "triage", "heal",
          "report"]


def _project(args) -> tuple[Project, Store]:
    p = Project(args.project)
    return p, Store(p.db_path)


def _live_session(project: Project, label: str) -> None:
    """Every run gets a Live View session folder, so it can be watched or replayed."""
    if os.environ.get("AGENTQA_LIVE_DIR"):
        return
    root = project.state / "live"
    root.mkdir(exist_ok=True)
    folder = root / f"cli-{time.strftime('%Y%m%d-%H%M%S')}-{label}"
    os.environ["AGENTQA_LIVE_DIR"] = str(folder)
    lc = project.cfg.get("live", {})
    os.environ.setdefault("AGENTQA_LIVE_SHOTS", "1" if lc.get("screenshots", True) else "0")
    os.environ.setdefault("AGENTQA_LIVE_QUALITY", str(lc.get("quality", 50)))
    sessions = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
    for old in sessions[:-int(project.cfg.get("live", {}).get("keep_sessions", 15))]:
        import shutil
        shutil.rmtree(old, ignore_errors=True)


def stage(name: str, project: Project, store: Store, args) -> dict:
    agent = {"analyze": "srs", "write": "writer", "explore": "explorer", "reconcile": "reconciler", "design": "designer",
             "generate": "generator", "run": "executor", "triage": "triage", "heal": "healer",
             "report": "reporter", "exploratory": "exploratory", "import": "importer", "security": "security"}.get(name, name)
    live.emit(agent, "stage_start", f"{name} started", stage=name)
    started = time.time()
    rid = store.insert("stage_runs", {"pipeline": os.environ.get("AGENTQA_PIPELINE_ID", "single"), "stage": name,
                                      "status": "running", "started_at": now(), "finished_at": None, "outputs": None,
                                      "error": None})
    try:
        out = _stage(name, project, store, args)
    except BaseException as exc:
        store.update("stage_runs", "id", rid, {"status": "failed", "finished_at": now(), "error": str(exc)[:800]})
        raise
    contract = None
    if name in ("analyze", "write", "design", "run", "triage"):
        from agentqa import contracts
        try:
            contract = contracts.validate(name, project, store)
        except Exception as exc:  # noqa: BLE001
            contract = {"ok": False, "violations": [f"the contract check failed: {exc}"], "violation_count": 1, "checked": 0}
        if not contract["ok"]:
            log(f"[{name}] contract: {contract['violation_count']} issue(s), e.g. {'; '.join(contract['violations'][:3])}")
            live.emit(agent, "contract", f"{name}: {contract['violation_count']} hand-over issue(s): "
                      f"{contract['violations'][0]}", level="warn")
    raw = json.dumps(out, default=str)
    store.update("stage_runs", "id", rid, {"status": "done", "finished_at": now(), "outputs": {
        "result": json.loads(raw) if len(raw) < 20000 else {"note": f"{len(raw)} bytes, see the log"}, "contract": contract}})
    live.emit(agent, "stage_end", f"{name} finished in {time.time() - started:.1f}s", stage=name,
              result=out if isinstance(out, dict) else None)
    return out


def _stage(name: str, project: Project, store: Store, args) -> dict:
    from agentqa.agents import (designer, executor, explorer, generator, healer, reconciler, reporter,
                                srs_analyst, triage)
    if name == "analyze":
        return srs_analyst.analyze(project, store, use_llm=getattr(args, "llm", None))
    if name == "explore":
        return explorer.explore(project, store, roles=getattr(args, "roles", None))
    if name == "reconcile":
        return reconciler.reconcile(project, store, policy=getattr(args, "policy", None))
    if name == "write":
        from agentqa.agents import req_writer
        return req_writer.write(project, store, use_llm=getattr(args, "llm", None))
    if name == "design":
        return designer.design(project, store)
    if name == "generate":
        return generator.generate(project, store)
    if name == "run":
        ctype = getattr(args, "type", None)
        if ctype:
            # e.g. 'run --type functional': regenerate the approved tests, run that kind only, then draft the defects
            generator.generate(project, store)
            only = [r["id"] for r in store.all("SELECT id FROM cases WHERE type=? AND status='approved' ORDER BY seq", [ctype])]
            if not only:
                raise RuntimeError(f"No approved {ctype} cases. Approve them on the Test plan or Functional tests page.")
            out = executor.run(project, store, only=only)
            out["triage"] = triage.triage(project, store)
            return out
        only = getattr(args, "only", None)
        if only or getattr(args, "all_approved", False):
            # a chosen set (or every approved case) from the Execution page: regenerate, run, then draft the defects
            generator.generate(project, store)
            out = executor.run(project, store, only=only or None)
            out["triage"] = triage.triage(project, store)
            return out
        return executor.run(project, store)
    if name == "exploratory":
        from agentqa.agents import exploratory
        return exploratory.explore(project, store, roles=getattr(args, "roles", None))
    if name == "security":
        from agentqa.agents import zapscan
        return zapscan.scan(project, store)
    if name == "triage":
        out = triage.triage(project, store)
        from agentqa.integrations import trackers
        if trackers.configured(project.cfg) and (trackers.trackers_cfg(project.cfg).get("sync") or {}).get("auto"):
            try:
                out["sync"] = trackers.sync(project, store)
            except Exception as exc:  # noqa: BLE001
                log(f"  tracker sync failed: {exc}")
        return out
    if name == "heal":
        return healer.heal(project, store)
    if name == "report":
        return reporter.report(project, store)
    raise ValueError(name)


def cmd_stage(args):
    p, s = _project(args)
    _live_session(p, args.cmd)
    job_id = getattr(args, "job_id", None)
    started = time.time()
    try:
        log(f"[{args.cmd}] {p.name}")
        out = stage(args.cmd, p, s, args)
        log(f"[{args.cmd}] done in {time.time() - started:.0f}s: {json.dumps(out, default=str)[:900]}")
        if job_id:
            s.update("jobs", "id", job_id, {"status": "done", "finished_at": now(), "exit_code": 0})
    except Exception as exc:  # noqa: BLE001
        log(f"[{args.cmd}] FAILED: {exc}")
        traceback.print_exc()
        if job_id:
            s.update("jobs", "id", job_id, {"status": "failed", "finished_at": now(), "exit_code": 1})
        sys.exit(1)


def resume_point(s: Store) -> tuple[str, str | None, list[str]] | None:
    """The last pipeline, the first stage it did not finish (None when all did), and the stages it finished."""
    last = s.one("SELECT pipeline FROM stage_runs WHERE pipeline LIKE 'pl-%' ORDER BY id DESC LIMIT 1")
    if not last:
        return None
    pid = last["pipeline"]
    finished = {r["stage"] for r in s.all("SELECT stage FROM stage_runs WHERE pipeline=? AND status IN ('done', 'skipped')",
                                          [pid])}
    return pid, next((x for x in STAGES if x not in finished), None), [x for x in STAGES if x in finished]


def cmd_pipeline(args):
    from agentqa.agents import designer
    p, s = _project(args)
    _live_session(p, "pipeline")
    live.emit("pipeline", "stage_start", f"Pipeline started for {p.name}", stage="pipeline", base_url=p.base_url,
              roles=list(p.roles()))
    job_id = getattr(args, "job_id", None)
    start = args.start
    pid = f"pl-{time.strftime('%Y%m%d-%H%M%S')}"
    if getattr(args, "resume", False):
        found = resume_point(s)
        if found is None:
            log("[pipeline] no earlier pipeline to resume; starting from the beginning")
        else:
            pid, start, finished = found
            if start is None:
                log(f"[pipeline] {pid} already finished every stage; nothing to resume")
                return
            log(f"[pipeline] resuming {pid} at '{start}' ({len(finished)} stage(s) already done: {', '.join(finished)})")
    os.environ["AGENTQA_PIPELINE_ID"] = pid
    order = STAGES[STAGES.index(start):]
    try:
        for name in order:
            if name == "generate":
                plan = s.one("SELECT approved FROM plan WHERE id=1")
                if args.auto_approve:
                    n = designer.approve(s)
                    log(f"[gate] auto-approved {n} case(s) (--auto-approve)")
                elif not (plan and plan["approved"]):
                    s.insert("stage_runs", {"pipeline": pid, "stage": "generate", "status": "waiting for plan approval",
                                            "started_at": now(), "finished_at": None, "outputs": None, "error": None})
                    live.emit("pipeline", "gate", "Stopped at the plan gate: a QA lead must approve the test plan",
                              level="warn")
                    log("[gate] STOP: the test plan needs a QA lead's approval. Review it in the web UI (Plan page) "
                        "or run 'agentqa approve --all', then continue with 'agentqa pipeline --from generate'.")
                    break
            if name == "design":
                _import_pending(p, s, approve=bool(args.auto_approve))
            if name == "exploratory" and not p.cfg.get("exploratory", {}).get("enabled", True):
                log("[exploratory] skipped (exploratory.enabled is false)")
                s.insert("stage_runs", {"pipeline": pid, "stage": name, "status": "skipped", "started_at": now(),
                                        "finished_at": now(), "outputs": {"why": "exploratory.enabled is false"}, "error": None})
                continue
            started = time.time()
            log(f"[{name}] starting")
            out = stage(name, p, s, args)
            log(f"[{name}] done in {time.time() - started:.0f}s: {json.dumps(out, default=str)[:600]}")
            if name == "reconcile":
                q = s.scalar("SELECT COUNT(*) FROM questions WHERE status='open'")
                if q:
                    live.emit("pipeline", "gate", f"{q} question(s) wait in the clarification queue", level="warn")
                    log(f"[gate] {q} question(s) wait in the clarification queue. Rules behind them are not tested "
                        f"until answered; everything else continues.")
        if job_id:
            s.update("jobs", "id", job_id, {"status": "done", "finished_at": now(), "exit_code": 0})
    except Exception as exc:  # noqa: BLE001
        log(f"[pipeline] FAILED: {exc}")
        traceback.print_exc()
        if job_id:
            s.update("jobs", "id", job_id, {"status": "failed", "finished_at": now(), "exit_code": 1})
        sys.exit(1)


def _import_pending(p: Project, s: Store, approve: bool = False) -> None:
    """Import manual test sheets dropped in the project's imports folder that were not imported yet."""
    from agentqa.agents import importer
    folder = p.root / "imports"
    if not folder.exists():
        return
    done = {r["source_file"] for r in s.all("SELECT DISTINCT source_file FROM manual_cases")}
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() in (".xlsx", ".xlsm", ".csv") and f.name not in done and not f.name.startswith("~$"):
            out = importer.import_file(p, s, f)
            log(f"[import] {f.name}: {out['cases']} case(s), {out['ready']} fully automated, {out['review']} need review")
            if approve:
                ids = [r["id"] for r in s.all("SELECT id FROM manual_cases WHERE status='ready' AND source_file=?", [f.name])]
                importer.set_status(s, ids, "approved")
                log(f"[gate] auto-approved {len(ids)} imported case(s) (--auto-approve)")


def cmd_teach_login(args):
    """A person shows AgentQA how to log in as a role: the path and the details they type are recorded and saved."""
    from playwright.sync_api import sync_playwright
    from agentqa import login_flow
    p, s = _project(args)
    _live_session(p, f"teach-{args.role}")
    job_id = getattr(args, "job_id", None)
    started = time.time()
    try:
        with sync_playwright() as pw:
            headed = os.environ.get("AGENTQA_HEADED") == "1"
            try:
                browser = pw.chromium.launch(headless=not headed)
            except Exception:  # noqa: BLE001  (no screen here: the box in the dashboard is enough)
                os.environ["AGENTQA_HEADED"] = "0"
                browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()
            try:
                used = login_flow.teach(page, p, args.role)
            except login_flow.LoginError as exc:
                login_flow._auth_log(p, args.role, "failed", str(exc), "teach", time.time() - started)
                raise
            login_flow.save_session(ctx, page, p, args.role, used)
            login_flow._auth_log(p, args.role, "ok", "logged in as you showed" + (" (with an OTP)" if used else ""),
                                 "teach", time.time() - started)
            browser.close()
        log(f"[teach-login] {args.role}: learned; the next login repeats your steps")
        if job_id:
            s.update("jobs", "id", job_id, {"status": "done", "finished_at": now(), "exit_code": 0})
    except Exception as exc:  # noqa: BLE001
        log(f"[teach-login] FAILED: {exc}")
        if job_id:
            s.update("jobs", "id", job_id, {"status": "failed", "finished_at": now(), "exit_code": 1})
        sys.exit(1)


def cmd_teach_nav(args):
    """A person shows AgentQA around as a role: pages they open are mapped and the way is remembered."""
    from agentqa.agents import explorer
    p, s = _project(args)
    _live_session(p, f"teach-nav-{args.role}")
    job_id = getattr(args, "job_id", None)
    try:
        out = explorer.teach_nav(p, s, args.role)
        log(f"[teach-nav] {args.role}: {out['shown']} page(s) shown and remembered")
        if job_id:
            s.update("jobs", "id", job_id, {"status": "done", "finished_at": now(), "exit_code": 0})
    except Exception as exc:  # noqa: BLE001
        log(f"[teach-nav] FAILED: {exc}")
        if job_id:
            s.update("jobs", "id", job_id, {"status": "failed", "finished_at": now(), "exit_code": 1})
        sys.exit(1)


def cmd_init(args):
    cfg = init_project(args.dir, args.name or Path(args.dir).name, args.url)
    log(f"Created {cfg}. Edit roles and login settings, put SRS files in {Path(args.dir) / 'srs'}, then run:\n"
        f"  python -m agentqa pipeline --project {args.dir}")


def cmd_questions(args):
    _, s = _project(args)
    rows = s.all("SELECT * FROM questions WHERE status=? ORDER BY id", ["open" if not args.all else "answered"])
    for q in rows:
        log(f"\n#{q['id']} [{q['priority']}] {q['question']}")
        if q.get("proposed"):
            log(f"   proposed: {q['proposed']}")
        for i, o in enumerate(q["options"] or []):
            log(f"   {i}) {o}")
        if q["status"] == "answered":
            log(f"   answered: {q['answer']} {q['answer_value']}")
    if not rows:
        log("No questions.")


def cmd_answer(args):
    from agentqa.agents.reconciler import answer_question
    _, s = _project(args)
    answer_question(s, args.id, args.choice, args.value or "")
    log(f"Answered #{args.id}. Re-run 'reconcile' and 'design' to apply it.")


def cmd_approve(args):
    from agentqa.agents import designer
    _, s = _project(args)
    n = designer.approve(s, case_types=args.type, case_ids=args.ids, reject=args.reject)
    log(f"{'Rejected' if args.reject else 'Approved'} {n} case(s).")


def cmd_defects(args):
    from agentqa.agents.triage import set_defect_status
    _, s = _project(args)
    if args.confirm:
        set_defect_status(s, args.confirm, "confirmed")
    if args.reject:
        set_defect_status(s, args.reject, "rejected", args.note or "")
    for d in s.all("SELECT * FROM defects ORDER BY seq"):
        log(f"{d['id']} [{d['severity']}] {d['status']:<9} {d['title']}")


def cmd_heal_approve(args):
    from agentqa.agents.healer import approve_heal
    p, s = _project(args)
    note = approve_heal(s, args.id, approve=not args.reject, project=p)
    if note:
        log(note)
    log("Done. Run 'generate' and 'run' to use the healed test.")


def cmd_sync(args):
    from agentqa.integrations import trackers
    p, s = _project(args)
    if args.test:
        for r in trackers.test_connection(p.cfg) or [{"system": "-", "ok": False, "detail": "no tracker is enabled"}]:
            log(f"{r['system']}: {'OK' if r['ok'] else 'FAILED'} - {r['detail']}")
        return
    _live_session(p, "sync")
    log(json.dumps(trackers.sync(p, s, push=not args.pull_only, pull=not args.push_only)))


def cmd_export_cases(args):
    from agentqa import case_export
    p, s = _project(args)
    out = Path(args.out)
    out.write_bytes(case_export.workbook(p, s, include_srs=not args.functional_only))
    log(f"Wrote {out.resolve()}")


def cmd_demo_ai(args):
    log(f"Stand-in AI provider APIs on http://127.0.0.1:{args.port} (see demo/mock_ai.py for the test keys)")
    subprocess.run([sys.executable, "-m", "demo.mock_ai", str(args.port)], cwd=str(Path(__file__).resolve().parent.parent))


def cmd_ai_test(args):
    from agentqa.ai import gateway
    gw = gateway()
    keys = gw.store.keys()
    if not keys:
        log("No AI keys yet. Add them on the AI providers page.")
        return
    bad = 0
    for k in keys:
        if k.get("status", "active") != "active":
            log(f"  {k.get('label')} ({k['provider']}): disabled")
            continue
        bad += not gw.test(k["id"])["ok"]
    sys.exit(1 if bad else 0)


def cmd_demo_trackers(args):
    root = Path(__file__).resolve().parent.parent
    log(f"Mock Jira and Azure DevOps on http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    subprocess.run([sys.executable, "-m", "uvicorn", "demo.mock_trackers:app", "--port", str(args.port),
                    "--log-level", "warning"], cwd=str(root))


def cmd_inbox(args):
    from agentqa import inbox
    p = Project(args.project)
    s = inbox.settings(p.cfg)
    srv = inbox.InboxServer(p.state / "inbox.db", args.host or s["host"], args.port or s["http_port"],
                            args.smtp_port if args.smtp_port is not None else s["smtp_port"]).start()
    log(f"Mock inbox for {p.name}: SMS webhook http://{srv.host}:{srv.http_port}/sms, SMTP {srv.host}:{srv.smtp_port}. "
        f"Messages: http://{srv.host}:{srv.http_port}/messages  (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def cmd_doctor(args):
    from agentqa import doctor
    p, s = _project(args)
    _live_session(p, "doctor")
    out = doctor.run(p, s, apply=args.apply)
    for c in out["checks"]:
        log(f"  [{c['status'].upper():4}] {c['name']}: {c['detail']}" + (f"\n         fix: {c['fix']}" if c.get("fix") else ""))
    log(f"Pilot readiness: {out['verdict']} ({out['ok']} ok, {out['warn']} to improve, {out['fail']} blocking)")
    if out["fail"] and not getattr(args, "job_id", None):
        sys.exit(1)   # from the dashboard the check itself succeeded; the page shows what blocks the pilot


def cmd_jira(args):
    from agentqa.agents.triage import push_jira
    p, s = _project(args)
    log(json.dumps(push_jira(p, s)))


def cmd_import(args):
    from agentqa.agents import importer
    p, s = _project(args)
    _live_session(p, "import")
    out = importer.import_file(p, s, Path(args.file))
    log(json.dumps(out))
    if args.approve_ready:
        ids = [m["id"] for m in s.all("SELECT id FROM manual_cases WHERE status='ready'")]
        importer.set_status(s, ids, "approved")
        log(f"Approved {len(ids)} fully converted case(s) for automation. Run 'design' to add them to the plan.")
    for m in s.all("SELECT id, status, coverage, title FROM manual_cases ORDER BY id"):
        log(f"  {m['id']:<8} {m['status']:<9} {m['coverage']:.0%}  {m['title']}")


def cmd_ask(args):
    from agentqa.agents import assistant
    p, s = _project(args)
    out = assistant.answer(p, s, " ".join(args.question))
    log(assistant.as_text(out))


def cmd_ci(args):
    from agentqa import readiness
    p, s = _project(args)
    _live_session(p, "ci")
    order = STAGES[STAGES.index(args.start):]
    started = time.time()
    for name in order:
        if name in ("heal",):
            continue
        if name == "exploratory" and (args.skip_exploratory or not p.cfg.get("exploratory", {}).get("enabled", True)):
            continue
        if name == "generate":
            plan = s.one("SELECT approved FROM plan WHERE id=1")
            if not (plan and plan["approved"]):
                log("[ci] the test plan is not approved; approve it in the dashboard or with 'agentqa approve --all'")
                sys.exit(2)
        log(f"[ci] {name}")
        stage(name, p, s, args)
    r = readiness.compute(p, s)
    run_id = s.get_meta("last_run")
    order_sev = ["Critical", "High", "Medium", "Low"]
    limit = order_sev.index(args.fail_on) if args.fail_on in order_sev else -1
    blocking = [d for d in s.all("SELECT * FROM defects WHERE status IN ('draft','confirmed','exported') AND run_id=?",
                                 [run_id]) if order_sev.index(d["severity"]) <= limit]
    log(f"[ci] readiness {r['score']}/100 ({r['verdict']}); {len(blocking)} open defect(s) at {args.fail_on} or worse; "
        f"{time.time() - started:.0f}s; JUnit: {p.runs_dir / run_id / 'junit.xml'}")
    for d in blocking:
        log(f"  {d['id']} [{d['severity']}] {d['title']}")
    if blocking or (args.min_score and r["score"] < args.min_score):
        sys.exit(1)


def cmd_llm_check(args):
    from agentqa.llm import check
    p, _ = _project(args)
    log(check(p.cfg["llm"], p))


def cmd_owner_set(args):
    """Create or replace the owner sign-in for the API: writes backend/.env (git-ignored) with the password hash."""
    import getpass
    import secrets
    from agentqa.api.auth import hash_password
    from agentqa.api.settings import DOTENV, MIN_SECRET_LEN
    email = (args.email or input("Owner email: ")).strip().lower()
    if "@" not in email:
        sys.exit("That is not an email address")
    password = getpass.getpass("Owner password (typed hidden): ")
    if len(password) < 10:
        sys.exit("Use at least 10 characters")
    if password != getpass.getpass("Repeat the password: "):
        sys.exit("The two passwords differ")
    existing = {}
    if DOTENV.exists():
        for line in DOTENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()
    secret = existing.get("AGENTQA_SECRET_KEY", "")
    if len(secret) < MIN_SECRET_LEN:
        secret = secrets.token_urlsafe(48)
    existing.update({"AGENTQA_OWNER_EMAIL": email, "AGENTQA_OWNER_PASSWORD_HASH": hash_password(password),
                     "AGENTQA_SECRET_KEY": secret})
    text = ("# AgentQA Studio owner sign-in. Keep this file private; it is git-ignored.\n"
            + "".join(f"{k}={v}\n" for k, v in existing.items()))
    fd = os.open(DOTENV, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)     # owner-only where the OS honours modes
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    log(f"Owner {email} saved to {DOTENV}. Restart the dashboard (python -m agentqa ui) to use it.")


def cmd_ui(args):
    import uvicorn
    os.environ["AGENTQA_PROJECTS"] = str(Path(args.projects_dir).resolve())
    log(f"AgentQA Studio UI on http://{args.host}:{args.port}  (projects folder: {os.environ['AGENTQA_PROJECTS']})")
    uvicorn.run("agentqa.api.server:app", host=args.host, port=args.port, log_level="warning")


def cmd_demo_project(args):
    import shutil
    root = Path(__file__).resolve().parent.parent
    dest = Path(args.dir)
    (dest / "srs").mkdir(parents=True, exist_ok=True)
    shutil.copy(root / "demo" / "project.yaml", dest / "project.yaml")
    for f in (root / "demo" / "srs").glob("*.docx"):
        shutil.copy(f, dest / "srs" / f.name)
    if (root / "demo" / "manual_tests.xlsx").exists():
        (dest / "imports").mkdir(exist_ok=True)
        shutil.copy(root / "demo" / "manual_tests.xlsx", dest / "imports" / "manual_tests.xlsx")
    log(f"Demo project ready in {dest}. Start the portal ('agentqa demo-portal'), then run:\n"
        f"  python -m agentqa pipeline -p {dest} --policy srs_wins --auto-approve")


def cmd_demo_portal(args):
    root = Path(__file__).resolve().parent.parent
    host = getattr(args, "host", "127.0.0.1")
    if getattr(args, "single", False):
        log(f"Demo portal (one site) on http://{host}:{args.port}  (Ctrl+C to stop)")
        subprocess.run([sys.executable, "-m", "uvicorn", "demo.portal.app:app", "--host", host, "--port", str(args.port),
                        "--log-level", "warning"], cwd=str(root))
        return
    log(f"Demo Citizen Portal on http://{host}:{args.port} and Department Portal on http://{host}:{args.dept_port}"
        "  (Ctrl+C to stop)")
    subprocess.run([sys.executable, "-m", "demo.portal.serve", "--host", host, "--port", str(args.port),
                    "--dept-port", str(args.dept_port)], cwd=str(root))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="agentqa", description="AgentQA Studio: local autonomous web testing")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_project(sp):
        sp.add_argument("--project", "-p", default=".", help="project folder (contains project.yaml)")
        sp.add_argument("--job-id", type=int, help=argparse.SUPPRESS)
        return sp

    sp = sub.add_parser("init", help="create a project folder")
    sp.add_argument("dir")
    sp.add_argument("--url", required=True, help="base URL of the test environment")
    sp.add_argument("--name")
    sp.set_defaults(func=cmd_init)

    for name, helptext in [("analyze", "Requirement Analyst: read the requirement documents into requirements and rules"),
                           ("write", "Requirement Writer: rewrite each requirement into clear wording, steps and criteria"),
                           ("explore", "Explorer: log in as each role and map every screen"),
                           ("reconcile", "Reconciler: compare SRS with the app, raise questions"),
                           ("design", "Planner + Designer: build the test plan and cases"),
                           ("generate", "Generator: write pytest + Playwright code for approved cases"),
                           ("run", "Executor: run the suite"),
                           ("exploratory", "Exploratory Tester: curious-user walk, odd inputs, other roles' URLs, "
                                           "security smoke"),
                           ("security", "Security Scanner: OWASP ZAP baseline and logged-in scan (if ZAP is installed)"),
                           ("triage", "Triage: group failures into defect drafts"),
                           ("heal", "Healer: propose fixes for broken locators"),
                           ("report", "Reporter: HTML report, RTM and defect CSV")]:
        sp = with_project(sub.add_parser(name, help=helptext))
        if name == "analyze":
            sp.add_argument("--llm", action="store_true", default=None, help="use the local model for unclear text")
        if name in ("explore", "exploratory"):
            sp.add_argument("--roles", nargs="*")
        if name == "reconcile":
            sp.add_argument("--policy", choices=["ask", "srs_wins", "app_wins"])
        if name == "run":
            sp.add_argument("--only", nargs="*", help="case ids, e.g. TC-0001 TC-0002")
            sp.add_argument("--type", help="run one kind of case, e.g. functional (generates first, drafts defects after)")
            sp.add_argument("--all-approved", action="store_true",
                            help="regenerate and run every approved case, then draft the defects")
        sp.set_defaults(func=cmd_stage)

    sp = with_project(sub.add_parser("pipeline", help="run every stage, stopping at the plan-approval gate"))
    sp.add_argument("--from", dest="start", choices=STAGES, default="analyze")
    sp.add_argument("--policy", choices=["ask", "srs_wins", "app_wins"])
    sp.add_argument("--auto-approve", action="store_true", help="skip the plan gate (demos only)")
    sp.add_argument("--resume", action="store_true", help="continue the last pipeline from the first stage it did not finish")
    sp.add_argument("--llm", action="store_true", default=None)
    sp.set_defaults(func=cmd_pipeline)

    sp = with_project(sub.add_parser("teach-login", help="log in once yourself in AgentQA's browser; it learns the steps"))
    sp.add_argument("--role", required=True)
    sp.set_defaults(func=cmd_teach_login)

    sp = with_project(sub.add_parser("teach-nav", help="show AgentQA around as a role; pages you open are mapped and remembered"))
    sp.add_argument("--role", required=True)
    sp.set_defaults(func=cmd_teach_nav)

    sp = with_project(sub.add_parser("export-cases", help="write the functional test cases (with last results) to Excel"))
    sp.add_argument("--out", default="functional-test-cases.xlsx")
    sp.add_argument("--functional-only", action="store_true", help="leave out the SRS-rule form and access checks")
    sp.set_defaults(func=cmd_export_cases)

    sp = with_project(sub.add_parser("questions", help="list the clarification queue"))
    sp.add_argument("--all", action="store_true", help="show answered questions")
    sp.set_defaults(func=cmd_questions)
    sp = with_project(sub.add_parser("answer", help="answer a question: answer <id> <option number> [--value]"))
    sp.add_argument("id", type=int)
    sp.add_argument("choice", type=int)
    sp.add_argument("--value")
    sp.set_defaults(func=cmd_answer)
    sp = with_project(sub.add_parser("approve", help="approve (or reject) test cases: the plan gate"))
    sp.add_argument("--type", nargs="*")
    sp.add_argument("--ids", nargs="*")
    sp.add_argument("--reject", action="store_true")
    sp.add_argument("--all", action="store_true")
    sp.set_defaults(func=cmd_approve)
    sp = with_project(sub.add_parser("defects", help="list, confirm or reject defects: the bug gate"))
    sp.add_argument("--confirm", nargs="*")
    sp.add_argument("--reject", nargs="*")
    sp.add_argument("--note")
    sp.set_defaults(func=cmd_defects)
    sp = with_project(sub.add_parser("heal-approve", help="approve or reject a Healer proposal"))
    sp.add_argument("id", type=int)
    sp.add_argument("--reject", action="store_true")
    sp.set_defaults(func=cmd_heal_approve)
    with_project(sub.add_parser("export-jira", help="create Jira issues for confirmed defects (v0.3; see sync)")).set_defaults(func=cmd_jira)
    sp = with_project(sub.add_parser("sync", help="two-way sync with Jira or Azure DevOps"))
    sp.add_argument("--push-only", action="store_true")
    sp.add_argument("--pull-only", action="store_true")
    sp.add_argument("--test", action="store_true", help="only test the connection")
    sp.set_defaults(func=cmd_sync)
    sp = with_project(sub.add_parser("inbox", help="run the mock SMS/email inbox for OTPs (keeps running)"))
    sp.add_argument("--host")
    sp.add_argument("--port", type=int)
    sp.add_argument("--smtp-port", type=int)
    sp.set_defaults(func=cmd_inbox)
    sp = with_project(sub.add_parser("doctor", help="pilot readiness check: environment, logins, OTP, SRS, tools"))
    sp.add_argument("--apply", action="store_true", help="write detected login selectors into project.yaml")
    sp.set_defaults(func=cmd_doctor)
    sp = with_project(sub.add_parser("import", help="import manual test cases from Excel or CSV and convert them"))
    sp.add_argument("file")
    sp.add_argument("--approve-ready", action="store_true", help="approve every fully converted case for automation")
    sp.set_defaults(func=cmd_import)
    sp = with_project(sub.add_parser("ask", help="ask the assistant about requirements, tests, results or defects"))
    sp.add_argument("question", nargs="+")
    sp.set_defaults(func=cmd_ask)
    sp = with_project(sub.add_parser("ci", help="run the approved suite for CI/CD and fail the build on new defects"))
    sp.add_argument("--from", dest="start", choices=STAGES, default="run")
    sp.add_argument("--fail-on", choices=["Critical", "High", "Medium", "Low", "none"], default="High")
    sp.add_argument("--min-score", type=int, default=0, help="also fail below this readiness score (0-100)")
    sp.add_argument("--skip-exploratory", action="store_true")
    sp.set_defaults(func=cmd_ci)
    with_project(sub.add_parser("llm-check", help="check the optional local model")).set_defaults(func=cmd_llm_check)

    sp = sub.add_parser("ui", help="start the web UI")
    sp.add_argument("--port", type=int, default=8700)
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--projects-dir", default="projects")
    sp.set_defaults(func=cmd_ui)
    sp = sub.add_parser("owner-set", help="create or replace the owner sign-in for the API (writes backend/.env)")
    sp.add_argument("--email", default="")
    sp.set_defaults(func=cmd_owner_set)
    sp = sub.add_parser("demo-ai", help="start stand-ins for the AI provider APIs (port 8950), to try key failover")
    sp.add_argument("--port", type=int, default=8950)
    sp.set_defaults(func=cmd_demo_ai)
    sp = sub.add_parser("ai-test", help="Test connection for every AI key on the AI providers page")
    sp.set_defaults(func=cmd_ai_test)
    sp = sub.add_parser("demo-project", help="create the demo project folder")
    sp.add_argument("dir", nargs="?", default="projects/demo")
    sp.set_defaults(func=cmd_demo_project)
    sp = sub.add_parser("demo-trackers", help="start the mock Jira and Azure DevOps (port 8900)")
    sp.add_argument("--port", type=int, default=8900)
    sp.set_defaults(func=cmd_demo_trackers)
    sp = sub.add_parser("demo-portal", help="start the demo Citizen Portal (8800) and Department Portal (8810)")
    sp.add_argument("--dept-port", type=int, default=8810)
    sp.add_argument("--single", action="store_true", help="one site with every page (versions before 0.6)")
    sp.add_argument("--port", type=int, default=8800)
    sp.add_argument("--host", default="127.0.0.1", help="interface to listen on (0.0.0.0 inside a container)")
    sp.set_defaults(func=cmd_demo_portal)

    args = ap.parse_args(argv)
    try:
        args.func(args)
    except SystemExit as exc:
        _finish_job(args, 1 if exc.code not in (None, 0) else 0)
        raise
    except BaseException:
        _finish_job(args, 1)
        raise
    _finish_job(args, 0)


def _finish_job(args, code: int) -> None:
    """Mark a dashboard job finished when its command did not do it itself."""
    job_id = getattr(args, "job_id", None)
    if not job_id:
        return
    try:
        p, s = _project(args)
        job = s.one("SELECT status FROM jobs WHERE id=?", [job_id])
        if job and job["status"] == "running":
            s.update("jobs", "id", job_id, {"status": "done" if code == 0 else "failed", "finished_at": now(), "exit_code": code})
    except Exception:  # noqa: BLE001
        pass
