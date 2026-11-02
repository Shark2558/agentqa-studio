"""Fixtures for AgentQA generated tests (copied into the project's tests folder).

Each test asks for a page per role; saved login sessions are reused, and on
failure a screenshot and a Playwright trace are kept as evidence.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

import agentqa_live as live
import agentqa_runtime as rt

live.get(os.environ.get("PYTEST_XDIST_WORKER") or ("tests-login" if os.environ.get("AGENTQA_PHASE") == "login" else "tests"))

HERE = Path(__file__).parent
SETTINGS = json.loads((HERE / "agentqa_settings.json").read_text(encoding="utf-8"))
RUN_DIR = Path(os.environ.get("AGENTQA_RUN_DIR", HERE.parent / "runs" / "adhoc"))
AUTH_DIR = Path(os.environ.get("AGENTQA_AUTH_DIR", HERE.parent / ".agentqa" / "auth"))
EVIDENCE = RUN_DIR / "evidence"
RESULTS: dict[str, dict] = {}
EVIDENCE_ALL = SETTINGS.get("evidence", "all") == "all"       # every test keeps a screenshot and a step log
VIDEO = bool(SETTINGS.get("video"))


def _blocked_roles() -> dict:
    f = AUTH_DIR / "blocked.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except ValueError:
        return {}


def pytest_configure(config):
    config.addinivalue_line("markers", "case(id): AgentQA test case id")
    rt.BLOCKED_ROLES.update(_blocked_roles())
    EVIDENCE.mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="session")
def browser():
    headed = os.environ.get("AGENTQA_HEADED") == "1"
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=not headed and SETTINGS.get("headless", True),
                               slow_mo=int(os.environ.get("AGENTQA_SLOWMO", "0")) if headed else 0)
        yield b
        b.close()


@pytest.fixture
def as_role(browser, request):
    opened: dict[str, tuple] = {}

    def open_role(role: str):
        if role in opened:
            return opened[role][1]
        state = AUTH_DIR / f"{role}.json"
        if role != "anonymous":
            why = _blocked_roles().get(role)
            if why or not state.exists():
                rt.blocked(f"the login for {role} did not work before this run ({why or 'no saved session'}), "
                           f"so this test cannot run as {role}")
        kw = {"record_video_dir": str(EVIDENCE / "video")} if VIDEO else {}
        ctx = browser.new_context(storage_state=str(state) if role != "anonymous" and state.exists() else None, **kw)
        ctx.set_default_timeout(int(SETTINGS.get("timeout_ms", 15000)))
        if SETTINGS.get("trace_on_failure"):
            ctx.tracing.start(screenshots=True, snapshots=True)
        page = ctx.new_page()
        page._aq_case = _case_id(request.node)
        page._aq_role = role
        page.console_errors = []
        page.net_errors = []
        page.on("console", lambda m: page.console_errors.append(m.text[:300]) if m.type == "error" else None)
        page.on("response", lambda r: page.net_errors.append(f"HTTP {r.status} {r.request.method} {r.url[:200]}")
                if r.status >= 400 else None)
        page.on("requestfailed", lambda q: page.net_errors.append(f"FAILED {q.method} {q.url[:200]}: {q.failure}"))
        opened[role] = (ctx, page)
        return page

    yield open_role

    rep = getattr(request.node, "rep_call", None)
    failed = bool(rep and rep.failed)
    case = _case_id(request.node)
    evidence = RESULTS.setdefault(request.node.nodeid, {}).setdefault("evidence", [])
    for role, (ctx, page) in opened.items():
        try:
            if failed or EVIDENCE_ALL:
                shot = EVIDENCE / (f"{case}-{role}.png" if failed else f"{case}-{role}.jpg")
                page.screenshot(path=str(shot), full_page=failed, **({} if failed else {"type": "jpeg", "quality": 60}))
                evidence.append({"kind": "screenshot", "role": role, "path": str(shot), "url": page.url,
                                 "when": "at the failure" if failed else "at the end"})
            if SETTINGS.get("trace_on_failure"):
                if failed:
                    trace = EVIDENCE / f"{case}-{role}-trace.zip"
                    ctx.tracing.stop(path=str(trace))
                    evidence.append({"kind": "trace", "role": role, "path": str(trace)})
                else:
                    ctx.tracing.stop()
        except Exception:  # noqa: BLE001
            pass
        video = page.video if VIDEO else None
        ctx.close()
        if video is not None:
            try:
                evidence.append({"kind": "video", "role": role, "path": str(video.path())})
            except Exception:  # noqa: BLE001
                pass
    # the step log: what was done, what was checked, console and network errors, times
    log = {"case": case, "nodeid": request.node.nodeid, "steps": list(rt.LOG), "verified": rt.VERIFIED["n"],
           "console_errors": [e for _, p in opened.values() for e in getattr(p, "console_errors", [])][:50],
           "network_errors": [e for _, p in opened.values() for e in getattr(p, "net_errors", [])][:50],
           "live_dir": os.environ.get("AGENTQA_LIVE_DIR"), "started": getattr(request.node, "aq_started", None),
           "finished": time.time()}
    if EVIDENCE_ALL or failed or opened:
        lf = EVIDENCE / f"{case}-log.json"
        lf.write_text(json.dumps(log, indent=1, default=str), encoding="utf-8")
        evidence.append({"kind": "log", "path": str(lf)})


def _case_id(item) -> str:
    m = item.get_closest_marker("case")
    return m.args[0] if m else item.name


def pytest_runtest_setup(item):
    rt.VERIFIED["n"] = 0
    rt.LOG.clear()
    item.aq_started = time.time()
    doc = (getattr(item, "function", None).__doc__ or "").strip().splitlines() if hasattr(item, "function") else []
    live.emit("executor", "test_start", f"{_case_id(item)}: {doc[0] if doc else item.name}", case=_case_id(item),
              nodeid=item.nodeid)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    unverified = rep.when == "call" and rep.passed and rt.VERIFIED["n"] == 0
    if unverified:
        # the browser steps ran, but no expected outcome was checked: that is not a pass
        rep.outcome = "failed"
        rep.longrepr = "NOT VERIFIED: the test finished without checking any expected result"
    setattr(item, f"rep_{rep.when}", rep)
    if rep.when == "call" or (rep.when == "setup" and rep.outcome != "passed"):
        msg = ""
        if call.excinfo is not None:
            msg = f"{call.excinfo.typename}: {call.excinfo.value}"[:3000]
        if unverified:
            msg = "NOT VERIFIED: the test finished without checking any expected result"
        if rep.when == "call":
            kind = ("defect" if "DEFECT:" in msg else "visual" if "VISUAL CHANGE:" in msg
                    else "blocked" if "BLOCKED:" in msg else "not-run" if "NOT RUN:" in msg
                    else ("passed" if rep.outcome == "passed" else "test-issue"))
            live.emit("executor", "test_end", f"{_case_id(item)} {kind}", case=_case_id(item), outcome=rep.outcome,
                      category=kind, duration=round(rep.duration, 2),
                      message=msg.replace("AssertionError: DEFECT: ", "")[:400] or None,
                      level={"passed": "ok", "defect": "bad", "visual": "warn"}.get(kind, "warn"))
        entry = RESULTS.setdefault(item.nodeid, {})
        entry.update({"nodeid": item.nodeid, "case_id": _case_id(item), "outcome": rep.outcome,
                      "duration": round(rep.duration, 2), "message": msg, "finished": time.time(),
                      "started": getattr(item, "aq_started", None)})


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    phase = os.environ.get("AGENTQA_PHASE", "")
    name = f"results-{phase + '-' if phase and phase != 'main' else ''}{worker}.json"
    if RESULTS:
        (RUN_DIR / name).write_text(json.dumps(list(RESULTS.values()), indent=1), encoding="utf-8")
