"""Functional test cases as a manual-tester workbook (Excel), with the last run's actual results.

Columns follow the standard template: TC ID, requirement IDs, module, scenario, objective, test type, priority
(Critical/High/Medium/Low), role, preconditions, test data, steps, expected result, actual result, status
(Passed/Failed/Blocked/Not Run), defect ID and evidence. A second sheet summarises by module. Values from the Test data page stay as descriptions ("the registered
mobile number"), never the values themselves.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

from agentqa import contracts
from agentqa.config import Project
from agentqa.store import Store
from agentqa.util import spreadsheet_safe, without_userinfo

SRS_FUNCTIONAL = {"form_valid": "Forms (SRS rules)", "field_rejects": "Forms (SRS rules)", "field_accepts": "Forms (SRS rules)",
                  "field_options": "Forms (SRS rules)", "field_attribute": "Forms (SRS rules)", "workflow": "Workflows",
                  "manual_converted": "Imported manual tests", "access_denied": "Access by role",
                  "security_otp": "Login", "record_isolation": "Access by role"}
SCENARIO = {"form_valid": "Positive", "field_accepts": "Boundary", "field_rejects": "Negative", "field_options": "Positive",
            "field_attribute": "Boundary", "workflow": "End to end", "manual_converted": "Imported", "access_denied": "Negative",
            "security_otp": "Negative", "record_isolation": "Negative"}


def rows(project: Project, store: Store, include_srs: bool = True, all_types: bool = False) -> list[dict]:
    """One row per test case, with its last result. By default only functional cases (and the SRS-derived
    functional checks when include_srs); with all_types, every prepared case (access, API, security, pages,
    accessibility, performance, visual...) so the whole suite exports under the standard template."""
    from agentqa.agents.triage import _steps
    if all_types:
        cases = store.all("SELECT * FROM cases ORDER BY seq")
    else:
        types = ["functional"] + (list(SRS_FUNCTIONAL) if include_srs else [])
        cases = store.all(f"SELECT * FROM cases WHERE type IN ({','.join('?' * len(types))}) ORDER BY seq", types)
    results = {}
    designed = store.scalar("SELECT MIN(created_at) FROM cases") or ""
    # the newest result per case from runs since the cases were designed (a functional-only run must not hide the
    # full run's results; case IDs from before a re-design may point at other cases)
    for r in store.all("SELECT r.case_id, r.outcome, r.category, r.message, r.run_id, r.evidence FROM results r JOIN runs u ON u.id = r.run_id "
                       "WHERE u.started_at >= ? ORDER BY u.started_at, r.rowid", [designed]):
        results[r["case_id"]] = r
    defects = {}
    for d in store.all("SELECT id, case_ids, status FROM defects WHERE status != 'rejected'"):
        for cid in d["case_ids"] or []:
            defects.setdefault(cid, d["id"])
    out = []
    for c in cases:
        p = c["params"] or {}
        res = results.get(c["id"])
        if c["type"] == "functional":
            module, scenario = p.get("module") or "Functional", p.get("scenario") or ""
            steps = p.get("steps_text") or []
            expected, pre, data = p.get("expected") or "", p.get("preconditions") or "", p.get("test_data") or ""
        elif c["type"] in SRS_FUNCTIONAL:
            module, scenario = SRS_FUNCTIONAL[c["type"]], SCENARIO.get(c["type"], "")
            steps = [re.sub(r"^\d+\.\s*", "", s) for s in _steps(c, project)]
            expected = c["title"]
            pre = "Logged out." if c["role"] == "anonymous" else f"Logged in as {c['role']}."
            data = _data(c)
        else:
            module, scenario = contracts._module(c), ""
            steps = [re.sub(r"^\d+\.\s*", "", s) for s in _steps(c, project)]
            expected = c["title"]
            pre = "Logged out." if c["role"] == "anonymous" else f"Logged in as {c['role']}."
            data = _data(c)
        actual, status, evidence = "", "Not Run", []
        if res:
            msg = re.sub(r"^(AssertionError: DEFECT: |Skipped: )", "", res["message"] or "")
            status = contracts.status_name(res["category"], res["message"] or "")
            actual = "As expected." if status == "Passed" else re.sub(r"^step \d+ \('[^']*'\):\s*", "", msg)[:600]
            evidence = [Path(str(e.get("path"))).name for e in (res.get("evidence") or []) if isinstance(e, dict) and e.get("path")]
        out.append({"id": c["id"], "module": module, "scenario": scenario, "title": c["title"], "role": c["role"],
                    "objective": contracts.objective(c), "test_type": contracts.test_type(c),
                    "priority": contracts.priority_name(c), "p": c["priority"], "reqs": ", ".join(c["req_ids"] or []),
                    "pre": pre, "data": data, "steps": steps, "expected": expected, "actual": actual, "status": status,
                    "defect": defects.get(c["id"], ""), "approved": c["status"], "type": c["type"], "path": c["path"],
                    "source": c["oracle_source"], "run_id": res["run_id"] if res else "", "evidence": evidence,
                    "by": p.get("generated_by") or ""})
    return out


def _data(c: dict) -> str:
    p = c["params"] or {}
    if c["type"] in ("field_rejects", "field_accepts"):
        return f"{p.get('label')}: " + "; ".join(p.get("descriptions") or [])
    if c["type"] == "form_valid":
        return "; ".join(f"{k}: {v}" for k, v in (p.get("values") or {}).items())
    if c["type"] == "field_options":
        return "Expected options: " + ", ".join(p.get("expected") or [])
    return ""


# The standard test case template the team uses, in order, then comprehensive extra columns after it.
# Each column: (header, how to read it from a row).
STD_COLUMNS = [
    ("Test Case Id", lambda r: r["id"]),
    ("User Access", lambda r: r["role"]),
    ("Module", lambda r: r["module"]),
    ("Test Case Name", lambda r: r["title"]),
    ("Test Case Description", lambda r: r["objective"] or r["title"]),
    ("Pre-Condition", lambda r: r["pre"]),
    ("Actions", lambda r: "\n".join(f"{i}. {s}" for i, s in enumerate(r["steps"], 1))),
    ("Test Data", lambda r: r["data"]),
    ("Expected Result", lambda r: r["expected"]),
    ("Test Result", lambda r: r["status"]),
    ("Remarks", lambda r: _remarks(r)),
]
EXTRA_COLUMNS = [
    ("Requirement ID", lambda r: r["reqs"]),
    ("Scenario", lambda r: r["scenario"]),
    ("Test Type", lambda r: r["test_type"]),
    ("Priority", lambda r: r["priority"]),
    ("Defect ID", lambda r: r["defect"]),
    ("Evidence", lambda r: "\n".join(f"runs/{r['run_id']}/evidence/{e}" for e in r["evidence"])),
]
_WIDTHS = {"Test Case Id": 11, "User Access": 12, "Module": 18, "Test Case Name": 40, "Test Case Description": 38,
           "Pre-Condition": 24, "Actions": 52, "Test Data": 26, "Expected Result": 40, "Test Result": 11, "Remarks": 40,
           "Requirement ID": 14, "Scenario": 12, "Test Type": 18, "Priority": 10, "Defect ID": 10, "Evidence": 30}


def _remarks(r: dict) -> str:
    if r["status"] == "Passed":
        return "As expected."
    bits = []
    if r["defect"]:
        bits.append(f"Defect {r['defect']}.")
    if r["actual"] and r["actual"] != "As expected.":
        bits.append(r["actual"])
    return " ".join(bits)


def _safe(values: list) -> list:
    """Text from the application under test (titles, steps, messages) is shown as text, never run as a formula."""
    return [spreadsheet_safe(v) for v in values]


def workbook(project: Project, store: Store, include_srs: bool = True, all_types: bool = True) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    data = rows(project, store, include_srs, all_types=all_types)
    cols = STD_COLUMNS + EXTRA_COLUMNS
    head = [h for h, _ in cols]
    wb = Workbook()
    ws = wb.active
    ws.title = "Test cases"
    blue, thin = "1D4ED8", Side(style="thin", color="D5DEEC")
    ws.append(_safe([f"{project.name}: test cases"]))
    ws["A1"].font = Font(bold=True, size=14, color=blue)
    run = store.get_meta("last_run") or "no run yet"
    ws.append(_safe([f"Applications: {', '.join(a['name'] + ' ' + without_userinfo(a['base_url']) for a in project.applications().values())} · "
                     f"last run {run} · {len(data)} case(s) · drafted by AgentQA Studio"]))
    ws["A2"].font = Font(italic=True, size=9, color="64748B")
    ws.append([])
    ws.append(head)
    for i, (h, _) in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = _WIDTHS.get(h, 16)
        cell = ws.cell(row=4, column=i)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=blue)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    fills = {"Passed": "DCFCE7", "Failed": "FEE2E2", "Blocked": "FEF3C7", "Not Run": "F1F5F9"}
    scol = head.index("Test Result") + 1
    for r in data:
        ws.append(_safe([fn(r) for _, fn in cols]))
        row = ws.max_row
        for col in range(1, len(head) + 1):
            c = ws.cell(row=row, column=col)
            c.alignment = Alignment(vertical="top", wrap_text=True)
            c.border = Border(bottom=thin)
        ws.cell(row=row, column=scol).fill = PatternFill("solid", fgColor=fills.get(r["status"], "FFFFFF"))
        ws.cell(row=row, column=scol).font = Font(bold=True)
    ws.freeze_panes = "B5"
    ws.auto_filter.ref = f"A4:{get_column_letter(len(head))}{ws.max_row}"

    sm = wb.create_sheet("Summary")
    sm.append(["Module", "Cases"] + contracts.STATUSES)
    for i, w in enumerate([26, 10, 10, 10, 10, 10], 1):
        sm.column_dimensions[get_column_letter(i)].width = w
        sm.cell(row=1, column=i).font = Font(bold=True, color="FFFFFF")
        sm.cell(row=1, column=i).fill = PatternFill("solid", fgColor=blue)
    mods: dict[str, dict] = {}
    for r in data:
        m = mods.setdefault(r["module"], {"n": 0, **{k: 0 for k in contracts.STATUSES}})
        m["n"] += 1
        m[r["status"]] += 1
    for name, m in mods.items():
        sm.append(_safe([name, m["n"]] + [m[k] for k in contracts.STATUSES]))
    sm.append(["Total", len(data)] + [sum(m[k] for m in mods.values()) for k in contracts.STATUSES])
    sm.cell(row=sm.max_row, column=1).font = Font(bold=True)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
