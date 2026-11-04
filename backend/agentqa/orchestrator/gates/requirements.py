"""Requirements (FR-ONB-4): the list a person reads, the four dispositions a person may set (covered and gap are
computed), and the traceability matrix download."""
from __future__ import annotations

from typing import Any

from agentqa.agents import requirements as reqs_agent
from agentqa.config import Project
from agentqa.orchestrator.gates import GateError, changelog, exports
from agentqa.store import Store

COLUMNS = "id, seq, section, text, kind, priority, roles, ambiguity, source_file, disposition, disposition_note"
DOCUMENTS = "SELECT name, kind, size, pages, segments, status, detail, read_at FROM documents ORDER BY name"


def listing(store: Store, limit: int = 200, offset: int = 0) -> dict[str, Any]:
    return {"requirements": store.all(f"SELECT {COLUMNS} FROM requirements ORDER BY seq LIMIT ? OFFSET ?", [limit, offset]),
            "documents": store.all(DOCUMENTS), "total": store.scalar("SELECT COUNT(*) FROM requirements") or 0}


def set_disposition(store: Store, rid: str, disposition: str, why: str, by: str) -> dict[str, Any]:
    if not store.scalar("SELECT COUNT(*) FROM requirements WHERE id=?", [rid]):
        raise GateError(404, "not_found", "No such requirement")
    reqs_agent.set_disposition(store, rid, disposition, changelog.clean_why(why), by=by)
    return store.one(f"SELECT {COLUMNS} FROM requirements WHERE id=?", [rid])


def rtm(project: Project, store: Store, by: str) -> tuple[bytes, str]:
    """The matrix as the engine writes it (its Excel half; a failed write is a 503, never an older file)."""
    data = exports.build(project, lambda scratch: reqs_agent.write_rtm(scratch, store)[1])
    changelog.record_download(store, "rtm.xlsx", "downloaded the traceability matrix (Excel)", by)
    return data, exports.download_name(project.name, "traceability.xlsx")
