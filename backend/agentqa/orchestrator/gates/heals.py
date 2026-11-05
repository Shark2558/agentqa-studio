"""Heals (M1.4 Phase C): the Healer's proposed fixes for tests broken by a changed screen, approved or rejected by a
person. Only a proposed locator or workflow fix can be decided (the others say "review this test by hand"); the
engine applies it (`healer.approve_heal`, which writes the change log with who) and its note comes back as it is."""
from __future__ import annotations

import threading
from typing import Any

from agentqa.agents import healer
from agentqa.config import Project
from agentqa.orchestrator import Busy
from agentqa.orchestrator.gates import GateError, changelog, need_why, run_going, where_clause
from agentqa.store import Store

DECIDABLE = ("locator", "workflow")
VALUE_MAX, REASON_MAX, CASE_IDS_MAX, NOTE_MAX = 200, 1000, 200, 300
ORDER = "(status!='proposed'), id DESC"
_DECIDING = threading.Lock()          # one decision at a time: a double-click cannot apply a fix twice


def _cap(value: Any, cap: int) -> Any:
    return value[:cap] if isinstance(value, str) else value


def _shown(stored: Any) -> dict[str, Any]:
    """The engine's old/new object, its plain values only, each text cut to VALUE_MAX (it comes from the tested site)."""
    if not isinstance(stored, dict):
        return {}
    return {str(k)[:40]: _cap(v, VALUE_MAX) for k, v in stored.items()
            if v is None or isinstance(v, (str, int, float, bool))}


def decidable(h: dict) -> bool:
    return h.get("status") == "proposed" and h.get("kind") in DECIDABLE


def item(h: dict) -> dict[str, Any]:
    return {"id": h["id"], "case_id": _cap(h.get("case_id"), CASE_IDS_MAX), "run_id": h.get("run_id"),
            "kind": h.get("kind"), "old": _shown(h.get("old")), "new": _shown(h.get("new")),
            "reason": _cap(h.get("reason") or "", REASON_MAX), "status": h.get("status"),
            "created_at": h.get("created_at"), "decidable": decidable(h)}


def listing(store: Store, status: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    where, params = where_clause({"status": status})
    rows = store.all(f"SELECT * FROM heals {where} ORDER BY {ORDER} LIMIT ? OFFSET ?", [*params, limit, offset])
    counts = {r["status"]: r["n"] for r in store.all("SELECT status, COUNT(*) n FROM heals GROUP BY status")}
    return {"items": [item(h) for h in rows], "counts": counts,
            "total": store.scalar(f"SELECT COUNT(*) FROM heals {where}", params) or 0}


def decide(project: Project, store: Store, hid: int, decision: str, why: str, by: str) -> dict[str, Any]:
    need_why(decision == "reject", why)
    with _DECIDING:
        if run_going(project, store):
            raise Busy("A run is going: decide on fixes once it has finished.")
        h = store.one("SELECT * FROM heals WHERE id=?", [hid])
        if not h:
            raise GateError(404, "not_found", "No such fix")
        if not decidable(h):
            raise GateError(409, "not_decidable", "This fix is not waiting for a decision, or must be made by hand")
        approve = decision == "approve"
        note = healer.approve_heal(store, hid, approve=approve, project=project, by=by, why=changelog.clean_why(why))
    return {"id": hid, "status": "approved" if approve else "rejected", "note": _cap(note, NOTE_MAX)}
