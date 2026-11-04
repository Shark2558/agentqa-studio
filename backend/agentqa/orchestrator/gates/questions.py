"""Gate 1, questions: the clarification queue as a person reads and answers it.

An answer only takes effect when the Reconciler runs again (fact 5), so `apply` starts `replan`; the queue never
stops the pipeline by itself."""
from __future__ import annotations

import json
from types import MappingProxyType
from typing import Any, Callable

from agentqa.agents import reconciler
from agentqa.agents import requirements as reqs_agent
from agentqa.config import Project
from agentqa.orchestrator.gates import GateError, changelog
from agentqa.store import Store

# The options that ask for a value, by question kind and option index (checked against reconciler.OPTIONS in tests).
VALUE_OPTIONS = MappingProxyType({"divergence": (2,), "srs_only_field": (1,), "srs_only_feature": (1,),
                                  "srs_only_screen": (1,), "ambiguous": (1,)})
PRIORITY = "CASE priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END"
COLUMNS = "id, key, kind, question, options, proposed, priority, req_id, rule_id, status, answer, answer_value, answered_at"


def _stored(q: dict) -> tuple[int | None, str]:
    try:
        v = json.loads(q.get("answer_value") or "{}")
        return (int(v["choice"]) if "choice" in v else None), str(v.get("value") or "")
    except (ValueError, TypeError, AttributeError):
        return None, ""


def item(q: dict) -> dict[str, Any]:
    needs = set(VALUE_OPTIONS.get(q["kind"], ()))
    choice, value = _stored(q) if q["status"] == "answered" else (None, "")
    return {"id": q["id"], "kind": q["kind"], "question": q["question"],
            "options": [{"label": str(o), "needs_value": i in needs} for i, o in enumerate(q["options"] or [])],
            "proposed": q["proposed"], "priority": q["priority"], "req_id": q["req_id"], "rule_id": q["rule_id"],
            "status": q["status"], "answer": None if q["answer"] is None else str(q["answer"]), "choice": choice,
            "value": value, "note_only": reqs_agent.note_only(q.get("key")),   # the key itself stays private
            "answered_at": q["answered_at"] if q["status"] == "answered" else None}


def listing(store: Store, status: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Open questions first, most important first; answered ones newest first."""
    where, params = ("WHERE status=?", [status]) if status else ("", [])
    order = "answered_at DESC, id DESC" if status == "answered" else f"(status != 'open'), {PRIORITY}, id"
    rows = store.all(f"SELECT {COLUMNS} FROM questions {where} ORDER BY {order} LIMIT ? OFFSET ?",
                     [*params, limit, offset])
    counts = {s: store.scalar("SELECT COUNT(*) FROM questions WHERE status=?", [s]) or 0 for s in ("open", "answered")}
    return {"items": [item(q) for q in rows], "counts": counts,
            "total": store.scalar(f"SELECT COUNT(*) FROM questions {where}", params) or 0}


DIVERGENCE_RULES = ("ask", "srs_wins", "app_wins")
ACCESS_RULES = ("ask", "deny", "ignore")


def policy(project: Project, store: Store) -> dict[str, str]:
    """The rules `replan` will reconcile with: the one the last run used (`source` "run", replan.POLICY_KEY), else
    project.yaml's (`source` "project"). An empty `policy:` or an unknown value reads as "ask", as the Reconciler
    treats it."""
    from agentqa.replan import remembered_policy          # the one reader replan uses too (no import loop either way)
    rules = project.cfg.get("policy") or {}
    remembered, divergence, access = remembered_policy(store), rules.get("divergence"), rules.get("inferred_access")
    if remembered:                                        # `source` names where the divergence rule comes from
        divergence, source = remembered, "run"
    else:
        divergence, source = (divergence if divergence in DIVERGENCE_RULES else "ask"), "project"
    return {"divergence": divergence, "inferred_access": access if access in ACCESS_RULES else "ask", "source": source}


def _get(store: Store, qid: int) -> dict:
    q = store.one(f"SELECT {COLUMNS} FROM questions WHERE id=?", [qid])
    if not q:
        raise GateError(404, "not_found", "No such question")
    return q


def answer(store: Store, qid: int, choice: int, value: str, by: str) -> dict[str, Any]:
    q = _get(store, qid)
    if q["status"] != "open":
        raise GateError(409, "not_open", "This question is already answered: reopen it first")
    options = q["options"] or []
    if not 0 <= choice < len(options):
        raise GateError(422, "validation", f"choice: pick one of the {len(options)} options")
    needs_value = choice in VALUE_OPTIONS.get(q["kind"], ())
    value = value.strip()
    if needs_value and not value:
        raise GateError(422, "validation", "value: this option needs a value; type it in the box")
    reconciler.answer_question(store, qid, choice, value if needs_value else "", by=by)
    return item(_get(store, qid))


def reopen(store: Store, qid: int, why: str, by: str) -> dict[str, Any]:
    q = _get(store, qid)
    if q["status"] != "answered":
        raise GateError(409, "not_answered", "This question is not answered yet")
    store.update("questions", "id", qid, {"status": "open", "answer": None, "answer_value": None})   # as the old page
    changelog.record(store, "question", qid, f"reopened (was '{q['answer']}')", why, by)
    return item(_get(store, qid))


def apply(project: Project, store: Store, by: str, spawn: Callable[..., int]) -> int:
    """Start `replan` (Reconciler then Designer) so the answers take effect; Busy while another job runs."""
    answered = store.scalar("SELECT COUNT(*) FROM questions WHERE status='answered'") or 0
    job_id = spawn(project, store, ["replan"], "replan")
    changelog.record(store, "plan", "-", f"asked to re-plan with {answered} answered question(s)", "", by)
    return job_id
