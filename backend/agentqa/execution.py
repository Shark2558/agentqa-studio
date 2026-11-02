"""Execution dashboard numbers: every case with its last result since the plan was designed.

Statuses follow the standard template (Passed, Failed, Blocked, Not Run) plus "Pending approval" for cases a QA
lead has not approved. Nothing counts as Passed unless the run checked its expected result; Blocked and Not Run
are shown on their own, never folded into Passed.
"""
from __future__ import annotations

import json
from pathlib import Path

from agentqa import contracts
from agentqa.config import Project
from agentqa.store import Store

ORDER = ["Passed", "Failed", "Blocked", "Not Run", "Pending approval"]


def latest_results(store: Store) -> dict[str, dict]:
    designed = store.scalar("SELECT MIN(created_at) FROM cases") or ""
    out: dict[str, dict] = {}
    for r in store.all("SELECT r.*, u.started_at run_started FROM results r JOIN runs u ON u.id = r.run_id "
                       "WHERE u.started_at >= ? ORDER BY u.started_at, r.rowid", [designed]):
        out[r["case_id"]] = r
    return out


def _apps(project: Project, case: dict) -> list[str]:
    """The applications a case touches, in the order it reaches them (a workflow: citizen, department, citizen)."""
    seq: list[str] = []

    def add(app: str) -> None:
        if not seq or seq[-1] != app:
            seq.append(app)
    role = case.get("role")
    add(project.app_of(role) if role and role in project.roles() else project.split_path(case.get("path") or "/")[0])
    for st in (case.get("params") or {}).get("steps") or []:
        if not isinstance(st, dict):
            continue
        if st.get("role") and st["role"] in project.roles():
            add(project.app_of(st["role"]))
        elif str(st.get("path") or "").startswith("@"):
            add(project.split_path(st["path"])[0])
    return seq


def rows(project: Project, store: Store) -> list[dict]:
    res = latest_results(store)
    defects: dict[str, str] = {}
    for d in store.all("SELECT id, case_ids FROM defects WHERE status != 'rejected' ORDER BY seq"):
        for cid in d["case_ids"] or []:
            defects.setdefault(cid, d["id"])
    names = {aid: a["name"] for aid, a in project.applications().items()}
    out = []
    for c in store.all("SELECT * FROM cases ORDER BY seq"):
        r = res.get(c["id"])
        view = contracts.case_view(c)
        if c["status"] != "approved":
            status = "Pending approval"
        elif r is None:
            status = "Not Run"
        else:
            status = contracts.status_name(r["category"], r["message"] or "")
        apps = _apps(project, c)
        ev = [e for e in (r["evidence"] or []) if isinstance(e, dict)] if r and isinstance(r["evidence"], list) else []
        out.append({"id": c["id"], "title": c["title"], "type": c["type"], "module": view["module"],
                    "test_type": view["test_type"], "priority": view["priority"], "role": c["role"],
                    "apps": [names.get(a, a) for a in apps], "req_ids": c["req_ids"] or [], "status": status,
                    "approved": c["status"], "run_id": r["run_id"] if r else "", "message": (r["message"] or "")[:300] if r else "",
                    "defect": defects.get(c["id"], ""), "evidence": ev, "workflow": view["module"] == "Workflows"
                    or c["type"] == "workflow", "scenario": view["scenario"]})
    return out


def _tally(rows_: list[dict], key) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows_:
        for k in dict.fromkeys(key(r) if callable(key) else [r[key]]):
            t = out.setdefault(k or "-", {"n": 0, **{s: 0 for s in ORDER}})
            t["n"] += 1
            t[r["status"]] += 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["n"]))


def _workflow_progress(project: Project, r: dict) -> dict:
    """How far a workflow case got: the step log in its evidence."""
    log_file = next((Path(e["path"]) for e in r["evidence"] if e.get("kind") == "log" and e.get("path")), None)
    steps, verified, last = 0, 0, ""
    if log_file and log_file.exists():
        try:
            data = json.loads(log_file.read_text(encoding="utf-8"))
            entries = data.get("steps") if isinstance(data, dict) else data
            for e in entries or []:
                if e.get("kind") in ("action", "verified"):
                    steps += 1
                if e.get("kind") == "verified":
                    verified += 1
                last = e.get("text") or last
        except (ValueError, OSError):
            pass
    return {"steps": steps, "verified": verified, "last": last[:160]}


def summary(project: Project, store: Store) -> dict:
    data = rows(project, store)
    k = {s: sum(1 for r in data if r["status"] == s) for s in ORDER}
    reqs = store.all("SELECT id, text, std, disposition FROM requirements ORDER BY seq")
    by_req = {}
    for q in reqs:
        mine = [r for r in data if q["id"] in r["req_ids"]]
        t = {"n": len(mine), **{s: sum(1 for r in mine if r["status"] == s) for s in ORDER}}
        t["title"] = ((q["std"] or {}).get("title") or q["text"])[:90]
        t["disposition"] = q["disposition"] or "gap"
        t["verdict"] = ("Failing" if t["Failed"] else "Passing" if t["n"] and t["Passed"] == t["n"] else
                        "Not complete" if t["n"] else "No test")
        by_req[q["id"]] = t
    open_defects = store.all("SELECT * FROM defects WHERE status NOT IN ('rejected', 'resolved') ORDER BY seq")
    workflows = []
    for r in data:
        if r["workflow"]:
            workflows.append({**r, **_workflow_progress(project, r)})
    return {
        "rows": data,
        "kpi": {"requirements": len(reqs), "requirements_mapped": sum(1 for v in by_req.values() if v["n"]),
                "cases": len(data), "mapped": sum(1 for r in data if r["req_ids"]),
                "pending": k["Pending approval"], "executed": k["Passed"] + k["Failed"] + k["Blocked"],
                "passed": k["Passed"], "failed": k["Failed"], "blocked": k["Blocked"], "not_run": k["Not Run"],
                "defects": len(open_defects)},
        "by_module": _tally(data, "module"), "by_app": _tally(data, lambda r: r["apps"]),
        "by_role": _tally(data, "role"), "by_type": _tally(data, "test_type"), "by_req": by_req,
        "workflows": workflows, "defects": open_defects,
        "skipped": {"production": store.get_meta("production_skipped") or [],
                    "no_case": store.get_meta("casegen_skipped") or []},
        "last_run": store.one("SELECT * FROM runs ORDER BY started_at DESC LIMIT 1"),
    }


def select(project: Project, store: Store, scope: str, value: str = "", ids: list[str] | None = None) -> list[str]:
    """Approved case IDs for a run scope: module, role, application, test type, workflows, failed, left, selected."""
    data = [r for r in rows(project, store) if r["approved"] == "approved"]
    pick = {
        "module": lambda r: r["module"] == value, "role": lambda r: r["role"] == value,
        "app": lambda r: value in r["apps"], "type": lambda r: r["test_type"] == value,
        "workflows": lambda r: r["workflow"], "failed": lambda r: r["status"] in ("Failed", "Blocked"),
        "left": lambda r: r["status"] == "Not Run", "selected": lambda r: r["id"] in set(ids or []),
        "requirement": lambda r: value in r["req_ids"],
    }.get(scope)
    if pick is None:
        raise ValueError(scope)
    return [r["id"] for r in data if pick(r)]
