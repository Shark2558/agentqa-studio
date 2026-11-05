"""The human gates of the new app (M1.4): questions, the test plan, defects and requirement dispositions, each a thin
service over the engine's own functions that also records who decided and why in the change log (FR-ACC-3)."""
from __future__ import annotations

from typing import Any

from agentqa.store import Store


class GateError(Exception):
    """A decision the gate refuses: `status` and `code` say how the API answers (404, 409, 422 or 503)."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(status, code, message)
        self.status, self.code, self.message = status, code, message


def need_why(required: bool, why: str) -> None:
    """Decision 4: a reason is required to reject or to undo a decision."""
    if required and not why:
        raise GateError(422, "validation", "why: give a short reason to reject or undo a decision")


def known_ids(store: Store, table: str, ids: list[str], what: str) -> list[str]:
    """The ids once each, in the order given; 422 for an empty list or naming the first few that do not exist.
    `table` is always a literal from the caller, never input."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise GateError(422, "validation", f"ids: choose at least one {what}")
    found = {r["id"] for r in store.all(f"SELECT id FROM {table} WHERE id IN ({','.join('?' * len(ids))})", ids)}
    unknown = [i for i in ids if i not in found]
    if unknown:
        raise GateError(422, "validation", f"ids: no such {what}: {', '.join(unknown[:5])}")
    return ids


def run_going(project, store: Store) -> bool:
    """Whether a run of this project is going: a job the app started, or a command-line run (a run writes visual rows,
    baselines and heals of its own, and Pause must reach it)."""
    from agentqa.orchestrator import jobs, live
    return jobs.running(store) is not None or live.cli_run_going(project)


def where_clause(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    """`WHERE a=? AND b=?` and its values for the filters that are set (the names are literals from the caller)."""
    used = {column: value for column, value in filters.items() if value}
    if not used:
        return "", []
    return "WHERE " + " AND ".join(f"{column}=?" for column in used), list(used.values())
