from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi import Path as PathParam

from agentqa.api.auth import User, current_user
from agentqa.api.errors import ApiError, ok
from agentqa.api.routes_projects import store_or_404
from agentqa.api.schemas import RunIn
from agentqa.api.schemas_gates import ID_MAX
from agentqa.orchestrator.gates import changelog
from agentqa.orchestrator.jobs import running, spawn     # tests replace `spawn` on this module

router = APIRouter(prefix="/projects/{slug}/runs", dependencies=[Depends(current_user)])
LIST_LIMIT = 50
LOG_TAIL = 12_000
JobId = PathParam(ge=1, le=ID_MAX)


def _args(body: RunIn) -> tuple[list[str], str]:
    """The `python -m agentqa …` arguments for a run request (same choices as the dashboard's buttons)."""
    if body.scope == "pipeline":
        return ["pipeline"] + (["--policy", body.policy] if body.policy else []) + (["--auto-approve"] if body.auto_approve else []), "pipeline"
    if body.scope == "continue":
        return ["pipeline", "--from", "generate"], "continue"
    return [body.scope] + (["--policy", body.policy] if body.policy and body.scope in ("reconcile", "replan") else []), body.scope


def job_view(row: dict) -> dict:
    return {k: row.get(k) for k in ("id", "stage", "status", "started_at", "finished_at", "exit_code")}


@router.post("", status_code=202)
def start_run(slug: str, body: RunIn, user: User = Depends(current_user)):
    args, label = _args(body)
    with store_or_404(slug) as (p, s):
        job_id = spawn(p, s, args, label, headed=body.headed)      # Busy answers 409 through store_or_404
        if body.auto_approve and body.scope == "pipeline":          # FR-SCH-3: approving by itself is a choice, logged
            changelog.record(s, "plan", "-", "started a run that approves the test plan by itself", "", changelog.who(user))
        return ok(job_view(s.one("SELECT * FROM jobs WHERE id=?", [job_id])), status=202)


@router.get("")
def list_runs(slug: str):
    with store_or_404(slug) as (_, s):
        running(s)                                          # marks a dead "running" job as failed first
        return ok([job_view(j) for j in s.all("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", [LIST_LIMIT])])


@router.get("/{job_id}")
def get_run(slug: str, job_id: int = JobId):
    with store_or_404(slug) as (_, s):
        running(s)
        job = s.one("SELECT * FROM jobs WHERE id=?", [job_id])
    if not job:
        raise ApiError(404, "not_found", "No such run")
    return ok(job_view(job))


@router.get("/{job_id}/log")
def get_run_log(slug: str, job_id: int = JobId):
    with store_or_404(slug) as (_, s):
        job = s.one("SELECT * FROM jobs WHERE id=?", [job_id])
    if not job:
        raise ApiError(404, "not_found", "No such run")
    path = Path(job["log_path"] or "")
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    return ok({"status": job["status"], "log": text[-LOG_TAIL:]})
