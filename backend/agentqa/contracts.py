"""Agent contracts: who does what, what each stage must hand on, and the standard test case template.

Every pipeline stage is checked against its contract when it finishes (the result is kept with the stage's
checkpoint in stage_runs and shown on the Dashboard). A broken contract is reported, never hidden: a case with no
expected result, a Passed result without evidence, a defect without its requirement or URL.

The standard test case template (exports, dashboard, RTM):
  TC ID, Requirement ID, Module, Scenario, Objective, Test type, Priority (Critical/High/Medium/Low), Role,
  Preconditions, Test data, Steps, Expected result, Actual result, Status (Passed/Failed/Blocked/Not Run),
  Defect ID, Evidence
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

TEST_TYPES = ["Positive", "Negative", "Boundary", "Field validation", "Business rule", "Access control (RBAC)",
              "Authentication", "Session", "Workflow", "End to end", "Integration", "Persistence", "Exception handling",
              "Navigation", "Regression", "Security", "Accessibility", "Performance", "Visual", "API"]
PRIORITIES = ["Critical", "High", "Medium", "Low"]
STATUSES = ["Passed", "Failed", "Blocked", "Not Run"]

_BY_TYPE = {
    "access_denied": "Access control (RBAC)", "api_access": "Access control (RBAC)", "record_isolation": "Access control (RBAC)",
    "security_otp": "Authentication", "security_session": "Session", "security_csrf": "Security", "security_headers": "Security",
    "field_rejects": "Field validation", "field_accepts": "Boundary", "field_attribute": "Boundary",
    "field_options": "Field validation", "form_valid": "Positive", "workflow": "Workflow", "page_smoke": "Exception handling",
    "links_ok": "Navigation", "a11y_basic": "Accessibility", "performance_load": "Performance", "visual_snapshot": "Visual",
    "api_smoke": "API", "manual_converted": "Regression",
}
_BY_MODULE = {"Login": "Authentication", "Logout": "Session", "Navigation": "Navigation", "Search": None,
              "Workflows": "End to end", "Forms": None, "Requirements": None}
_CATEGORY_TYPE = {"Authentication": "Authentication", "Access control": "Access control (RBAC)", "Workflow": "Workflow",
                  "Field validation": "Field validation", "Performance": "Performance", "Security": "Security",
                  "Accessibility": "Accessibility", "Notification": "Integration", "Integration": "Integration",
                  "Usability": "Exception handling"}


def test_type(case: dict) -> str:
    p = case.get("params") or {}
    if p.get("test_type") in TEST_TYPES:
        return p["test_type"]
    if case.get("type") in _BY_TYPE:
        return _BY_TYPE[case["type"]]
    mod, scen = p.get("module") or "", str(p.get("scenario") or "")
    if mod == "Login" and re.search(r"session", (case.get("title") or "").lower()):
        return "Session"
    if mod == "Workflows":
        return "End to end" if "across" in scen or "→" in scen else "Workflow"
    if _BY_MODULE.get(mod):
        return _BY_MODULE[mod]
    for t in ("Negative", "Boundary", "Positive"):
        if scen.startswith(t):
            return t
    return "Positive"


def priority_name(case: dict) -> str:
    """P1 cases on logins, access and workflows are Critical; then P1 High, P2 Medium, P3 Low."""
    p = (case.get("priority") or "P2").upper()
    if p == "P1" and test_type(case) in ("Authentication", "Access control (RBAC)", "Workflow", "End to end", "Session"):
        return "Critical"
    return {"P0": "Critical", "P1": "High", "P2": "Medium", "P3": "Low"}.get(p, "Medium")


def objective(case: dict) -> str:
    p = case.get("params") or {}
    if p.get("objective"):
        return p["objective"]
    t = test_type(case)
    title = (case.get("title") or "").rstrip(".")
    verb = {"Negative": "Confirm the portal refuses it:", "Boundary": "Confirm the limit holds:",
            "Access control (RBAC)": "Confirm only permitted roles get in:", "Authentication": "Confirm the login works as specified:",
            "Session": "Confirm the session behaves as specified:", "Field validation": "Confirm the field rule holds:"}.get(t, "Confirm:")
    return f"{verb} {title[:1].lower() + title[1:]}" if title else ""


def status_name(category: str | None, message: str = "") -> str:
    """The run's own categories in the template's words. Only a checked outcome is Passed."""
    if category == "pass":
        return "Passed"
    if category in ("defect", "visual-change"):
        return "Failed"
    if category in ("not-run", "skipped", None) or "NOT RUN:" in (message or "")[:60]:
        return "Not Run"
    return "Blocked"   # login or precondition failed, environment down, or the test itself could not finish


class CaseStep(BaseModel):
    action: str
    text: str = ""


class TestCase(BaseModel):
    """The standard template, as one designed case must fill it."""
    tc_id: str = Field(pattern=r"^TC-\d{4,}$")
    req_ids: list[str]
    trace_note: str = ""
    module: str = Field(min_length=1)
    scenario: str = ""
    objective: str = Field(min_length=3)
    test_type: Literal[tuple(TEST_TYPES)]  # type: ignore[valid-type]
    priority: Literal[tuple(PRIORITIES)]  # type: ignore[valid-type]
    role: str = Field(min_length=1)
    preconditions: str = ""
    test_data: str = ""
    steps: list[str] = Field(min_length=1)
    expected: str = Field(min_length=3)

    @model_validator(mode="after")
    def traced(self):
        if not self.req_ids and not self.trace_note:
            raise ValueError("a case without a requirement must say what it checks instead (trace note)")
        return self


class Result(BaseModel):
    case_id: str
    status: Literal[tuple(STATUSES)]  # type: ignore[valid-type]
    evidence: list[str] = []
    message: str = ""

    @model_validator(mode="after")
    def evidence_for_verdicts(self):
        if self.status in ("Passed", "Failed") and not self.evidence:
            raise ValueError("a Passed or Failed result needs evidence")
        return self


class Defect(BaseModel):
    id: str
    finding: str = ""
    case_ids: list[str] = []
    req_ids: list[str] = []
    url: str = Field(min_length=4)
    created_at: str = Field(min_length=10)
    title: str = Field(min_length=3)
    expected: str = ""
    actual: str = Field(min_length=3)
    evidence: list[str] = []

    @model_validator(mode="after")
    def traced(self):
        if not self.case_ids and not self.finding:
            raise ValueError("a defect needs the test case(s) that found it, or the exploratory finding")
        return self


class StdRequirement(BaseModel):
    id: str
    title: str = Field(min_length=2)
    category: str
    actors: list[str] = Field(min_length=1)
    main_flow: list[str] = Field(min_length=1)
    expected_outcome: str = ""
    source: str = Field(min_length=2)


# ---- the agents --------------------------------------------------------------------------------
AGENTS = [
    {"name": "Requirement Analyst", "stage": "analyze", "module": "agents/srs_analyst.py + documents.py + requirements.py",
     "does": "reads every uploaded document (OCR for scans), keeps a ledger of every passage, extracts requirements and "
             "rules, flags vague text, duplicates and contradictions, sets each requirement's disposition",
     "reads": ["requirement documents"], "writes": ["documents", "segments", "requirements", "rules", "dispositions"],
     "after": []},
    {"name": "Requirement Writer", "stage": "write", "module": "agents/req_writer.py",
     "does": "rewrites each requirement into clear wording: statement, user story, steps, acceptance criteria, open "
             "points (AI model when set up); flags any number or role the source does not have",
     "reads": ["requirements", "rules", "screens"], "writes": ["requirements.std.written"],
     "after": ["Requirement Analyst", "Explorer"]},
    {"name": "Explorer", "stage": "explore", "module": "agents/explorer.py + login_flow.py",
     "does": "logs in as every role on every application (asking for OTPs), maps screens, forms and APIs",
     "reads": ["applications", "test data"], "writes": ["screens", "endpoints", "auth_log"], "after": []},
    {"name": "Reconciler", "stage": "reconcile", "module": "agents/reconciler.py",
     "does": "compares each rule with the live app; asks when they disagree", "reads": ["rules", "screens"],
     "writes": ["rules.status", "questions"], "after": ["Requirement Analyst", "Explorer"]},
    {"name": "Test Designer", "stage": "design", "module": "agents/designer.py",
     "does": "turns confirmed rules and the app map into cases; keeps production read-only",
     "reads": ["rules", "screens", "requirements.std"], "writes": ["cases", "plan"], "after": ["Reconciler"]},
    {"name": "Functional Test Analyst", "stage": "design", "module": "agents/analyst.py",
     "does": "login, session, navigation, form and search cases, written like a manual tester",
     "reads": ["screens", "login recordings", "test data"], "writes": ["cases"], "after": ["Explorer"]},
    {"name": "Workflow agent", "stage": "design", "module": "agents/workflows.py",
     "does": "multi-user workflows (submit, verify, approve, reject) across applications",
     "reads": ["status rules", "screens"], "writes": ["cases"], "after": ["Explorer", "Reconciler"]},
    {"name": "Test Case Generation agent", "stage": "design", "module": "agents/casegen.py",
     "does": "drafts template cases for requirements nothing else covered (model when configured, rules otherwise)",
     "reads": ["requirements.std.written", "screens"], "writes": ["cases"], "after": ["Requirement Writer", "Test Designer"]},
    {"name": "Generator", "stage": "generate", "module": "agents/generator.py",
     "does": "writes runnable Playwright tests from the approved cases", "reads": ["cases (approved)"],
     "writes": ["tests/"], "after": ["Test Designer"]},
    {"name": "Executor", "stage": "run", "module": "agents/executor.py + runtime/",
     "does": "runs the tests (logins first), keeps evidence for every test, marks Blocked when a login fails",
     "reads": ["tests/", "test data"], "writes": ["runs", "results", "evidence"], "after": ["Generator"]},
    {"name": "Visual QA agent", "stage": "run", "module": "agents/visual_qa.py",
     "does": "carries out intent steps and judges verify steps from screenshot, DOM and accessibility tree; quotes the page",
     "reads": ["the live page"], "writes": ["step log"], "after": ["Executor"]},
    {"name": "Exploratory tester", "stage": "exploratory", "module": "agents/exploratory.py",
     "does": "tries what a curious tester would (odd input, back button, double submit)", "reads": ["screens"],
     "writes": ["findings"], "after": ["Explorer"]},
    {"name": "Security scanner", "stage": "security", "module": "agents/zapscan.py",
     "does": "OWASP ZAP spider and passive scan; active scan only on test environments", "reads": ["applications"],
     "writes": ["findings"], "after": ["Explorer"]},
    {"name": "Triage", "stage": "triage", "module": "agents/triage.py",
     "does": "turns failures into defects with requirement, case, URL, time and logs", "reads": ["results", "findings"],
     "writes": ["defects"], "after": ["Executor"]},
    {"name": "Healer", "stage": "heal", "module": "agents/healer.py",
     "does": "proposes locator fixes for broken tests; never changes an expected result", "reads": ["results"],
     "writes": ["heals (proposed)"], "after": ["Executor"]},
    {"name": "Reporter", "stage": "report", "module": "agents/reporter.py",
     "does": "report, RTM and exports", "reads": ["everything"], "writes": ["reports/"], "after": ["Triage"]},
]
MAY_NOT_CHANGE = ("Execution agents (Executor, Visual QA, Healer) never change a requirement, rule or expected result. "
                  "A rule changes only by a person's answer or decision, recorded in the change log with the reason.")


# ---- checks at stage boundaries ----------------------------------------------------------------
def case_view(case: dict) -> dict:
    p = case.get("params") or {}
    steps = p.get("steps_text") or [s.get("text") or s.get("action") for s in p.get("steps") or []] or [case.get("title")]
    return {"tc_id": case["id"], "req_ids": case.get("req_ids") or [], "module": p.get("module") or _module(case),
            "trace_note": "" if case.get("req_ids") else f"checks the app itself ({case.get('oracle_source') or case['type']})",
            "scenario": str(p.get("scenario") or ""), "objective": objective(case), "test_type": test_type(case),
            "priority": priority_name(case), "role": case.get("role") or "anonymous",
            "preconditions": p.get("preconditions") or ("Logged out." if case.get("role") == "anonymous"
                                                         else f"Logged in as {case.get('role')}."),
            "test_data": str(p.get("test_data") or ""), "steps": [str(s) for s in steps if s],
            "expected": str((p.get("expected") if case.get("type") == "functional" else None) or case.get("title") or "")}


def _module(case: dict) -> str:
    return {"access_denied": "Access by role", "api_access": "Access by role", "record_isolation": "Access by role",
            "page_smoke": "Pages", "links_ok": "Navigation", "a11y_basic": "Accessibility", "visual_snapshot": "Visual",
            "performance_load": "Performance", "api_smoke": "APIs"}.get(case["type"], "Security" if case["type"].startswith(
                "security") else "Forms (SRS rules)" if case["type"].startswith(("field", "form")) else case["type"])


def _paths(ev) -> list[str]:
    return [str(e.get("path")) for e in (ev if isinstance(ev, list) else []) if isinstance(e, dict) and e.get("path")]


def _errors(model, data: dict) -> list[str]:
    try:
        model(**data)
        return []
    except ValidationError as exc:
        return [f"{'.'.join(str(x) for x in e['loc']) or '-'}: {e['msg']}" for e in exc.errors()]


def validate(stage: str, project, store) -> dict:
    """Check what a stage handed on. Returns {"checked", "violations": [...], "ok"}."""
    v: list[str] = []
    n = 0
    if stage == "analyze":
        for r in store.all("SELECT id, text, source_file FROM requirements"):
            n += 1
            if not (r["text"] or "").strip() or not r["source_file"]:
                v.append(f"{r['id']}: no text or no source document")
        for d in store.all("SELECT name, status, detail FROM documents WHERE status != 'read'"):
            v.append(f"document {d['name']} {d['status']}: {d['detail']}")
    elif stage == "write":
        for r in store.all("SELECT id, std FROM requirements"):
            n += 1
            w = (r["std"] or {}).get("written") or {}
            if not w.get("statement") or not w.get("steps"):
                v.append(f"{r['id']}: no rewritten statement or steps")
            for f in w.get("flags") or []:
                v.append(f"{r['id']}: {f}")
    elif stage == "design":
        for r in store.all("SELECT id, std FROM requirements"):
            n += 1
            st = r["std"] or {}
            v += [f"{r['id']} {e}" for e in _errors(StdRequirement, {"id": r["id"], **{k: st.get(k) for k in (
                "title", "category", "actors", "main_flow", "expected_outcome", "source")}})]
        for c in store.all("SELECT * FROM cases ORDER BY seq"):
            n += 1
            v += [f"{c['id']} {e}" for e in _errors(TestCase, case_view(c))]
    elif stage == "run":
        run_id = store.get_meta("last_run")
        for r in store.all("SELECT * FROM results WHERE run_id=?", [run_id]):
            n += 1
            ev = _paths(r["evidence"])
            st = status_name(r["category"], r["message"] or "")
            errs = _errors(Result, {"case_id": r["case_id"], "status": st, "evidence": ev, "message": r["message"] or ""})
            if not errs and ev and not any(Path(e).exists() for e in ev):
                errs = ["evidence files are missing on disk"]
            v += [f"{r['case_id']} {e}" for e in errs]
    elif stage == "triage":
        for d in store.all("SELECT * FROM defects WHERE status != 'rejected'"):
            n += 1
            v += [f"{d['id']} {e}" for e in _errors(Defect, {
                "id": d["id"], "finding": "" if d["case_ids"] else (d["signature"] or ""), "case_ids": d["case_ids"] or [], "req_ids": d["req_ids"] or [], "url": d["url"] or "",
                "created_at": d["created_at"] or "", "title": d["title"] or "", "expected": d["expected"] or "",
                "actual": d["actual"] or "", "evidence": _paths(d["evidence"])})]
    return {"checked": n, "violations": v[:40], "violation_count": len(v), "ok": not v}
