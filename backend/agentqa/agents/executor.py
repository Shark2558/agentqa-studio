"""Executor agent: refresh role sessions, run the suite, store results.

Runs pytest in a separate process (parallel with pytest-xdist when
available). No model is used: the same commit gives the same verdicts.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from agentqa.agents.explorer import login
from agentqa import live
from agentqa.config import Project, workers as config_workers
from agentqa.store import Store, now
from agentqa.util import log, warn


def _cookie_hashes(ctx) -> dict:
    return {c["name"]: hashlib.sha256(c["value"].encode()).hexdigest()[:16] for c in ctx.cookies()}


def _otp_reuse_check(browser, project: Project, role: str) -> None:
    """Log in twice; on the second login type the first login's OTP. A correct portal refuses it."""
    from agentqa import login_flow
    meta = {"role": role}
    steps = project.vault.login_steps(role)
    try:
        if not steps:
            raise RuntimeError("no recorded login for this role yet")
        ctx = browser.new_context()
        page = ctx.new_page()
        login_flow.replay(page, project, role, steps, agent="executor")
        first = login_flow.OTP_SEEN.get(role)
        ctx.close()
        if not first:
            raise RuntimeError("the first login did not use an OTP")
        ctx = browser.new_context()
        page = ctx.new_page()
        login_flow.OTP_OVERRIDE[role] = first
        try:
            login_flow.replay(page, project, role, steps, agent="executor")
            accepted = True
        except login_flow.LoginError:
            accepted = False
        finally:
            login_flow.OTP_OVERRIDE.pop(role, None)
        landed = project.rel(page.url)
        meta.update(reused_accepted=accepted, landed=landed)
        live.shot(page, "executor", "observe", f"Second login as {role} with the OTP already used in the first login: the portal "
                  f"{'ACCEPTED' if accepted else 'refused'} it (now on {landed})", level="bad" if accepted else "ok", role=role)
        ctx.close()
    except Exception as exc:  # noqa: BLE001
        meta["error"] = str(exc)[:300]
        warn(f"OTP reuse check for {role} could not run: {exc}")
    project.auth_file(f"{role}__otp.meta").write_text(json.dumps(meta), encoding="utf-8")


def refresh_sessions(project: Project, store: Store | None = None) -> list[str]:
    from agentqa import inbox
    if inbox.needed(project):
        inbox.ensure(project)
    from agentqa import login_flow
    ok = []
    blocked: dict[str, str] = {}
    roles = list(project.roles())
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for role in roles + project.peers():
            try:
                login_flow.ensure_session(browser, project, role, "executor")
                ok.append(role)
            except Exception as exc:  # noqa: BLE001
                warn(f"login for {role} failed: {exc}")
                blocked[role] = str(exc)[:300]
                live.emit("executor", "issue", f"Login for {role} failed: every test that needs {role} will be Blocked "
                          f"({str(exc)[:160]})", role=role, level="bad")
        # tests read this before opening a role: a role without a working login makes its tests Blocked, never Passed
        (project.state / "auth").mkdir(parents=True, exist_ok=True)
        (project.state / "auth" / "blocked.json").write_text(json.dumps(blocked, indent=1), encoding="utf-8")
        # a separate session for the logout test, so other tests keep a valid login; never one that needs
        # a person to type an OTP (that would ask you twice)
        sec_role = next((r for r in roles if not login_flow.needs_person(project, r)), None)
        if sec_role and project.cfg.get("security", {}).get("enabled", True):
            ctx = browser.new_context()
            page = ctx.new_page()
            try:
                page.goto(project.url((project.cfg["login"].get("start") or "/")), wait_until="load")
                before = _cookie_hashes(ctx)
                login(page, project, sec_role, agent="executor")
                after = _cookie_hashes(ctx)
                ctx.storage_state(path=str(project.auth_file(f"{sec_role}__sec")))
                project.auth_file(f"{sec_role}__sec.meta").write_text(json.dumps({"before": before, "after": after, "role": sec_role}),
                                                                       encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                warn(f"security login for {sec_role} failed: {exc}")
            ctx.close()
        otp_roles = [r for r in ((store.get_meta("otp_roles") or []) if store else [])
                     if login_flow.otp_source(project, r) in ("inbox", "api")]
        if otp_roles and project.cfg.get("security", {}).get("enabled", True):
            _otp_reuse_check(browser, project, otp_roles[0])
        browser.close()
    return ok


def classify(message: str) -> str:
    if not message:
        return "pass"
    if "BLOCKED:" in message:
        return "blocked"
    if "NOT RUN:" in message:
        return "not-run"
    if "DEFECT:" in message:
        return "defect"
    if "VISUAL CHANGE:" in message:
        return "visual-change"
    low = message.lower()
    if any(k in low for k in ("err_connection_refused", "net::err", "connection refused", "econnrefused")):
        return "environment"
    if any(k in low for k in ("locatormissing", "not found", "waiting for locator", "timeout", "strict mode")):
        return "test-issue"
    return "test-issue"


def run(project: Project, store: Store, only: list[str] | None = None) -> dict:
    if not (project.tests_dir / "conftest.py").exists():
        raise RuntimeError("No generated tests. Run 'agentqa generate' first.")
    run_id = datetime.now().strftime("run-%Y%m%d-%H%M%S")
    run_dir = project.runs_dir / run_id
    run_dir.mkdir(parents=True)
    from agentqa import testdata
    setup = testdata.run_steps(project, "setup", "run")
    log("  refreshing role sessions")
    refresh_sessions(project, store)
    store.insert("runs", {"id": run_id, "started_at": now(), "status": "running"})
    workers = config_workers(project.cfg)
    base = [sys.executable, "-m", "pytest", str(project.tests_dir), "-q", "--tb=no", "-rN"]
    if only:
        base += ["-k", " or ".join(c.lower().replace("-", "_") for c in only)]
    pkg_root = str(Path(__file__).resolve().parent.parent.parent)
    env = {**os.environ, "AGENTQA_RUN_DIR": str(run_dir), "AGENTQA_AUTH_DIR": str(project.state / "auth"),
           "AGENTQA_PROJECT_DIR": str(project.root), "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": os.pathsep.join([pkg_root] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))}
    log(f"  running {'in ' + str(workers) + ' parallel browsers' if workers > 1 else 'serially'}: {run_id}")
    total = store.scalar("SELECT COUNT(*) FROM cases WHERE status='approved'")
    live.emit("executor", "start", f"Running {len(only) if only else total} test(s) in {workers} browser(s)",
              run_id=run_id, total=len(only) if only else total, workers=workers)
    # phase 1: everything that uses the saved sessions, in parallel
    cmd = base + ["-m", "not aq_login", f"--junitxml={run_dir / 'junit.xml'}"]
    if workers > 1 and importlib.util.find_spec("xdist"):
        cmd += ["-n", str(workers)]
    proc = subprocess.run(cmd, cwd=str(project.tests_dir), env={**env, "AGENTQA_PHASE": "main"}, capture_output=True, text=True)
    out = proc.stdout + "\n" + proc.stderr
    # phase 2: tests that log in afresh (wrong OTPs, logout...), one at a time and last, so a portal that allows one
    # session per user, or sends one OTP at a time, does not disturb the other tests
    login_tests = any("aq_login" in f.read_text(encoding="utf-8") for f in project.tests_dir.glob("test_*.py"))
    if login_tests:
        live.emit("executor", "step", "Now the tests that log in afresh, one at a time (wrong OTPs, logout...)")
        proc2 = subprocess.run(base + ["-m", "aq_login", "-p", "no:xdist", f"--junitxml={run_dir / 'junit-login.xml'}"],
                               cwd=str(project.tests_dir), env={**env, "AGENTQA_PHASE": "login"}, capture_output=True, text=True)
        out += "\n---- login tests ----\n" + proc2.stdout + "\n" + proc2.stderr
    (run_dir / "pytest.log").write_text(out, encoding="utf-8")
    cleanup = testdata.run_steps(project, "cleanup", "run")
    if setup or cleanup:
        store.set_meta("data_last", {"run_id": run_id, "setup": setup, "cleanup": cleanup})
    results = []
    for f in sorted(run_dir.glob("results-*.json")):
        results += json.loads(f.read_text(encoding="utf-8"))
    if not results:
        store.update("runs", "id", run_id, {"status": "error", "finished_at": now()})
        raise RuntimeError(f"pytest produced no results; see {run_dir / 'pytest.log'}\n{out[-1500:]}")
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "changes": 0, "blocked": 0, "not_run": 0}
    _store_visual(store, run_dir, run_id)
    for r in results:
        outcome = r.get("outcome", "error")
        cat = "pass" if outcome == "passed" else classify(r.get("message", "") or "")
        if outcome == "skipped" and cat not in ("blocked", "not-run"):
            cat = "skipped"
        if outcome == "passed":
            counts["passed"] += 1
        elif cat == "blocked":
            counts["blocked"] += 1
        elif cat == "not-run":
            counts["not_run"] += 1
        elif outcome == "skipped":
            counts["skipped"] += 1
        elif cat == "defect":
            counts["failed"] += 1
        elif cat == "visual-change":
            counts["changes"] += 1
        else:
            counts["errors"] += 1
        started = datetime.fromtimestamp(r["started"]).isoformat(timespec="seconds") if r.get("started") else None
        store.insert("results", {"run_id": run_id, "case_id": r.get("case_id"), "outcome": outcome,
                                 "duration": r.get("duration"), "message": r.get("message", ""),
                                 "evidence": r.get("evidence", []), "nodeid": r.get("nodeid"), "category": cat,
                                 "started_at": started})
    store.update("runs", "id", run_id, {"finished_at": now(), "total": len(results), "status": "done", **counts})
    live.emit("executor", "summary", f"{counts['passed']} passed, {counts['failed']} defect(s), "
              f"{counts['errors']} test issue(s)" + (f", {counts['blocked']} blocked" if counts["blocked"] else "")
              + (f", {counts['not_run']} not run" if counts["not_run"] else "")
              + (f", {counts['changes']} visual change(s)" if counts["changes"] else "")
              + f" of {len(results)}", run_id=run_id, **counts)
    store.set_meta("last_run", run_id)
    return {"run_id": run_id, "total": len(results), **counts}


def _store_visual(store: Store, run_dir, run_id: str) -> None:
    """Record each visual snapshot result for the Visual review page."""
    for f in sorted((run_dir / "visual").glob("*.json")) if (run_dir / "visual").exists() else []:
        try:
            v = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        old = store.one("SELECT * FROM visual WHERE key=?", [v["key"]])
        status = v.get("status")
        if old and old["status"] == "approved" and status == "same":
            status = "approved"
        store.insert("visual", {"key": v["key"], "role": v.get("role"), "path": v.get("path"), "status": status,
                                "diff_ratio": v.get("ratio"), "baseline": v.get("baseline"), "current": v.get("current"),
                                "diff": v.get("diff"), "run_id": run_id, "case_id": v.get("case"), "updated_at": now()},
                     replace=True)
