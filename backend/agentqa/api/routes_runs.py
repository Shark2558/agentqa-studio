from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from agentqa.api.auth import current_user
from agentqa.api.errors import ApiError, ok
from agentqa.api.routes_projects import open_or_404
from agentqa.api.schemas import RunIn
from agentqa.orchestrator import Busy
from agentqa.orchestrator.jobs import running, spawn     # tests replace `spawn` on this module

router = APIRouter(prefix="/projects/{slug}/runs", dependencies=[Depends(current_user)])
LIST_LIMIT = 50
LOG_TAIL = 12_000


def _args(body: RunIn) -> tuple[list[str], str]:
    """The `python -m agentqa …` arguments for a run request (same choices as the dashboard's buttons)."""
    if body.scope == "pipeline":
        return ["pipeline"] + (["--policy", body.policy] if body.policy else []) + (["--auto-approve"] if body.auto_approve else []), "pipeline"
    if body.scope == "continue":
        return ["pipeline", "--from", "generate"], "continue"
    return [body.scope] + (["--policy", body.policy] if body.policy and body.scope == "reconcile" else []), body.scope


def _job(row: dict) -> dict:
    return {k: row.get(k) for k in ("id", "stage", "status", "started_at", "finished_at", "exit_code")}


@router.post("", status_code=202)
def start_run(slug: str, body: RunIn):
    p, s = open_or_404(slug)
    args, label = _args(body)
    try:
        job_id = spawn(p, s, args, label, headed=body.headed)
    except Busy as exc:
        raise ApiError(409, "busy", str(exc)) from exc
    return ok(_job(s.one("SELECT * FROM jobs WHERE id=?", [job_id])), status=202)


@router.get("")
def list_runs(slug: str):
    _, s = open_or_404(slug)
    running(s)                                              # marks a dead "running" job as failed first
    return ok([_job(j) for j in s.all("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", [LIST_LIMIT])])


@router.get("/{job_id}")
def get_run(slug: str, job_id: int):
    _, s = open_or_404(slug)
    running(s)
    job = s.one("SELECT * FROM jobs WHERE id=?", [job_id])
    if not job:
        raise ApiError(404, "not_found", "No such run")
    return ok(_job(job))


@router.get("/{job_id}/log")
def get_run_log(slug: str, job_id: int):
    _, s = open_or_404(slug)
    job = s.one("SELECT * FROM jobs WHERE id=?", [job_id])
    if not job:
        raise ApiError(404, "not_found", "No such run")
    path = Path(job["log_path"] or "")
    text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    return ok({"status": job["status"], "log": text[-LOG_TAIL:]})
