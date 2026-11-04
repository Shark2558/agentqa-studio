"""What is waiting for a person, in one read: the navigation badges, the Project page and the Live View use it (as the
old dashboard's counts did, web/app.py `_ctx`)."""
from __future__ import annotations

from typing import Any

from agentqa import assist
from agentqa.config import Project
from agentqa.orchestrator import jobs
from agentqa.orchestrator.gates.plan import imported_counts, plan_state
from agentqa.store import Store


def _count(store: Store, sql: str) -> int:
    return store.scalar(sql) or 0


def counts(project: Project, store: Store) -> dict[str, Any]:
    plan = plan_state(store)
    return {
        "questions_open": _count(store, "SELECT COUNT(*) FROM questions WHERE status='open'"),
        "plan": {"exists": plan["summary"] is not None, "approved": plan["approved"],
                 "proposed": _count(store, "SELECT COUNT(*) FROM cases WHERE status='proposed'"),
                 "cases": _count(store, "SELECT COUNT(*) FROM cases"), "digest": plan["digest"]},
        "imported_ready": imported_counts(store)["ready"],
        "defects_draft": _count(store, "SELECT COUNT(*) FROM defects WHERE status='draft'"),
        "defects_open": _count(store, "SELECT COUNT(*) FROM defects WHERE status NOT IN ('rejected','resolved')"),
        "visual_changed": _count(store, "SELECT COUNT(*) FROM visual WHERE status='changed'"),
        "heals_proposed": _count(store, "SELECT COUNT(*) FROM heals WHERE status='proposed'"),
        "assist_pending": _count(store, "SELECT COUNT(*) FROM assist WHERE status='pending'"),
        "paused": assist.paused(project),
        "running": jobs.running(store) is not None,
    }
