"""Gate 2, the test plan: what the Designer proposed, the decisions a person makes on it, and the approval.

Decisions are refused while a job runs (a re-design could overwrite them), and the plan is approved only against the
fingerprint (`digest`) the person reviewed: `designer.plan()` clears an approval whenever the case set changes."""
from __future__ import annotations

from typing import Any

from agentqa import case_export, live
from agentqa.agents import designer, importer
from agentqa.config import Project
from agentqa.orchestrator import jobs
from agentqa.orchestrator.gates import GateError, changelog, exports, known_ids, need_why, where_clause
from agentqa.store import Store

APPROVED_PREFIX = "approved the plan"
CASE_COLUMNS = "id, type, title, role, path, priority, oracle_source, req_ids, status"
CASE_VERBS = {"approve": "approved", "reject": "rejected", "reset": "sent {n} case(s) back to proposed"}
IMPORTED_STATUS = {"approve": "approved", "reject": "rejected", "review": "review"}
IMPORTED_VERBS = {"approved": "approved", "rejected": "rejected", "review": "sent back to review"}
LOG_IDS, GAP_MAX = 10, 200


def say_approved_earlier(store: Store) -> None:
    """The run-shell line for a continued run whose plan was approved before it started (the Live View's plan gate
    then reads "approved" instead of "not yet"): when, and who, from the plan approval in the change log, but only a
    row written for this approval (an approval by the command line writes none, and an older row is someone else's)."""
    approved_at = (store.one("SELECT approved_at FROM plan WHERE id=1") or {}).get("approved_at") or ""
    row = changelog.last(store, "plan", APPROVED_PREFIX)
    by = row["by"] if row and approved_at and row["at"] >= approved_at else None
    title = ("Test plan approved earlier" + (f", on {approved_at[:16].replace('T', ' ')}" if approved_at else "")
             + (f" by {by}" if by else ""))
    live.emit("designer", "approve", title, level="ok")


# ---- reading ------------------------------------------------------------------------------------

def plan_state(store: Store) -> dict[str, Any]:
    row = store.one("SELECT * FROM plan WHERE id=1")
    summary = (row or {}).get("summary") or None
    return {"approved": bool(row and row["approved"]), "approved_at": row["approved_at"] if row else None,
            "digest": (summary or {}).get("digest"), "summary": summary}


def _types(store: Store) -> list[dict[str, Any]]:
    rows = store.all("SELECT type, COUNT(*) n, SUM(status='approved') a, SUM(status='rejected') r, "
                     "SUM(status='proposed') p FROM cases GROUP BY type ORDER BY type")
    return [{"type": r["type"], "cases": r["n"], "approved": r["a"] or 0, "rejected": r["r"] or 0,
             "proposed": r["p"] or 0} for r in rows]


def _gaps(store: Store) -> dict[str, Any]:
    """What the plan does not cover yet (as the old Plan page showed it)."""
    def ids(disposition: str) -> list[str]:
        return [r["id"] for r in store.all("SELECT id FROM requirements WHERE disposition=? ORDER BY seq LIMIT ?",
                                           [disposition, GAP_MAX])]
    return {"untested": ids("gap"), "clarify": ids("clarify"),
            "unread": store.all("SELECT name, status, detail FROM documents WHERE status != 'read' LIMIT ?", [GAP_MAX]),
            "missed": store.scalar("SELECT COUNT(*) FROM segments WHERE disposition='possibly missed'") or 0,
            "workflow": (store.get_meta("workflow_gaps") or [])[:GAP_MAX],
            "production": (store.get_meta("production_skipped") or [])[:GAP_MAX]}


def imported_counts(store: Store) -> dict[str, int]:
    return {s: store.scalar("SELECT COUNT(*) FROM manual_cases WHERE status=?", [s]) or 0
            for s in ("ready", "review", "approved", "rejected")}


def overview(store: Store) -> dict[str, Any]:
    return {"plan": plan_state(store), "types": _types(store), "gaps": _gaps(store), "imported": imported_counts(store),
            "running": jobs.running(store) is not None}


def cases(store: Store, ctype: str | None = None, status: str | None = None, limit: int = 50,
          offset: int = 0) -> dict[str, Any]:
    where, params = where_clause({"type": ctype, "status": status})
    rows = store.all(f"SELECT {CASE_COLUMNS} FROM cases {where} ORDER BY seq LIMIT ? OFFSET ?", [*params, limit, offset])
    return {"items": rows, "total": store.scalar(f"SELECT COUNT(*) FROM cases {where}", params) or 0}


# ---- deciding -----------------------------------------------------------------------------------

def _not_running(store: Store) -> None:
    if jobs.running(store):
        raise GateError(409, "busy", "A run is going: decide on the plan when it has finished")


def preview(ids: list[str]) -> str:
    return ", ".join(ids[:LOG_IDS]) + (f" and {len(ids) - LOG_IDS} more" if len(ids) > LOG_IDS else "")


def decide_cases(store: Store, ids: list[str], decision: str, why: str, by: str) -> dict[str, Any]:
    need_why(decision in ("reject", "reset"), why)
    _not_running(store)
    ids = known_ids(store, "cases", ids, "case")             # never empty: designer.approve() would take every case
    if decision == "reset":
        for cid in ids:                                       # as the old Plan page's "reset"
            store.update("cases", "id", cid, {"status": "proposed"})
        n = len(ids)
    else:
        n = designer.approve(store, case_ids=ids, reject=decision == "reject")
    verb = CASE_VERBS[decision].format(n=n) if decision == "reset" else f"{CASE_VERBS[decision]} {n} case(s)"
    changelog.record(store, "case", ids[0] if len(ids) == 1 else f"{len(ids)} cases", f"{verb}: {preview(ids)}", why, by)
    return {"changed": n, "plan": plan_state(store)}


def decide_type(store: Store, ctype: str, decision: str, why: str, by: str) -> dict[str, Any]:
    need_why(decision == "reject", why)
    _not_running(store)
    if not store.scalar("SELECT COUNT(*) FROM cases WHERE type=?", [ctype]):
        raise GateError(422, "validation", "type: the plan has no cases of that type")
    n = designer.approve(store, case_types=[ctype], reject=decision == "reject")
    if n:
        changelog.record(store, "case", ctype, f"{CASE_VERBS[decision]} {n} {ctype} case(s)", why, by)
    return {"changed": n, "plan": plan_state(store)}


def decide_imported(store: Store, ids: list[str], decision: str, why: str, by: str) -> dict[str, Any]:
    need_why(decision in ("reject", "review"), why)
    _not_running(store)
    if decision == "approve_ready":
        ids, status = [r["id"] for r in store.all("SELECT id FROM manual_cases WHERE status='ready' ORDER BY id")], "approved"
    else:
        ids, status = known_ids(store, "manual_cases", ids, "imported case"), IMPORTED_STATUS[decision]
    n = importer.set_status(store, ids, status)
    if n:
        changelog.record(store, "imported case", ids[0] if n == 1 else f"{n} cases",
                         f"{IMPORTED_VERBS[status]} {n} imported case(s): {preview(ids)}", why, by)
    return {"changed": n, "plan": plan_state(store)}


def approve(store: Store, digest: str, why: str, by: str) -> dict[str, Any]:
    """Approve every case still proposed and the plan itself: only the plan the person reviewed, never mid-run."""
    _not_running(store)
    state = plan_state(store)
    if state["summary"] is None:
        raise GateError(409, "no_plan", "There is no test plan yet: run the pipeline as far as the plan first")
    if state["digest"] != digest:
        raise GateError(409, "plan_changed", "The plan changed since you opened it: review it again")
    designer.approve(store)
    counts = {s: store.scalar("SELECT COUNT(*) FROM cases WHERE status=?", [s]) or 0 for s in ("approved", "rejected")}
    changelog.record(store, "plan", "-", f"{APPROVED_PREFIX}: {counts['approved']} approved, {counts['rejected']} rejected",
                     why, by)
    return plan_state(store)


def workbook(project: Project, store: Store, by: str) -> tuple[bytes, str]:
    """Every prepared case in the standard template (built in memory by the engine's writer)."""
    data = case_export.workbook(project, store, include_srs=True, all_types=True)
    changelog.record_download(store, "testcases.xlsx", "downloaded the test cases (Excel)", by)
    return data, exports.download_name(project.name, "test-cases.xlsx")
