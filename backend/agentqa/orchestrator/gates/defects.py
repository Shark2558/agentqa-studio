"""Gate 3, defects: Triage's drafts as a person confirms, rejects (with a reason) or sends back to draft; the two CSV
downloads (confirmed defects only unless drafts are asked for, decision 5); evidence by index through `files`."""
from __future__ import annotations

from typing import Any

from agentqa.agents import triage
from agentqa.config import Project
from agentqa.orchestrator.gates import GateError, changelog, exports, files, known_ids, need_why, where_clause
from agentqa.store import Store

SEVERITY = "CASE severity WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END"
ORDER = f"(status IN ('rejected','resolved')), {SEVERITY}, seq"
FIELDS = ("id", "severity", "priority", "title", "role", "url", "steps", "expected", "actual", "req_ids", "case_ids",
          "status", "created_at", "notes", "external_key")
VERBS = {"confirmed": "confirmed", "rejected": "rejected", "draft": "sent back to draft"}
EXPORTS = {"jira": ("defects CSV", "defects.csv", triage.export_csv),
           "zoho": ("defects Zoho CSV", "defects-zoho.csv", triage.export_zoho_csv)}


def _entries(stored: Any) -> list:
    return stored if isinstance(stored, list) else []        # the column is JSON written by the engine: trust its shape no further


def _evidence(stored: Any) -> list[dict[str, Any]]:
    return [{"n": i, "kind": e.get("kind"), "role": e.get("role"), "image": files.is_image(e.get("path"))}
            for i, e in enumerate(_entries(stored)) if isinstance(e, dict)]


def item(d: dict) -> dict[str, Any]:
    return {**{k: d.get(k) for k in FIELDS}, "evidence": _evidence(d.get("evidence"))}


def listing(store: Store, status: str | None = None, severity: str | None = None, limit: int = 50,
            offset: int = 0) -> dict[str, Any]:
    where, params = where_clause({"status": status, "severity": severity})
    rows = store.all(f"SELECT * FROM defects {where} ORDER BY {ORDER} LIMIT ? OFFSET ?", [*params, limit, offset])
    open_by = {r["severity"]: r["n"] for r in store.all(
        "SELECT severity, COUNT(*) n FROM defects WHERE status NOT IN ('rejected','resolved') GROUP BY severity")}
    by_status = {r["status"]: r["n"] for r in store.all("SELECT status, COUNT(*) n FROM defects GROUP BY status")}
    return {"items": [item(d) for d in rows], "counts": {"open_by_severity": open_by, "by_status": by_status},
            "total": store.scalar(f"SELECT COUNT(*) FROM defects {where}", params) or 0}


def _not_exported(store: Store, ids: list[str]) -> None:
    """A defect already sent to a tracker is changed there: confirming it again would file it a second time."""
    sent = [r["id"] for r in store.all(
        f"SELECT id FROM defects WHERE id IN ({','.join('?' * len(ids))}) AND (status='exported' "
        "OR COALESCE(external_key, '') != '') ORDER BY seq", ids)]
    if sent:
        raise GateError(409, "exported", f"Already sent to the tracker, so change it there: {', '.join(sent[:5])}")


def decide(store: Store, ids: list[str], decision: str, why: str, by: str) -> dict[str, int]:
    """One status for several defects; the note on each says who and why, and each gets its own log row."""
    need_why(decision in ("rejected", "draft"), why)
    ids = known_ids(store, "defects", ids, "defect")
    _not_exported(store, ids)
    why = changelog.clean_why(why)
    triage.set_defect_status(store, ids, decision, note=f"{by}: {VERBS[decision]}" + (f" ({why})" if why else ""))
    for did in ids:
        changelog.record(store, "defect", did, VERBS[decision], why, by)
    return {"changed": len(ids)}


def export(project: Project, store: Store, kind: str, include_drafts: bool, by: str) -> tuple[bytes, str]:
    label, name, write = EXPORTS[kind]
    data = exports.build(project, lambda scratch: write(scratch, store, include_drafts=include_drafts))
    changelog.record_download(store, name, f"downloaded {label} ({'with' if include_drafts else 'without'} drafts)", by)
    return data, name


def evidence(project: Project, store: Store, did: str, n: int) -> files.SafeFile:
    d = store.one("SELECT evidence FROM defects WHERE id=?", [did])
    stored = _entries((d or {}).get("evidence"))
    entry = stored[n] if 0 <= n < len(stored) and isinstance(stored[n], dict) else None
    found = files.safe_file(project, entry.get("path")) if entry else None
    if found is None:
        raise GateError(404, "not_found", "No such evidence file")
    return found
