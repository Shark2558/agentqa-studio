"""Gate 1 — questions (M1.4): the clarification queue, answers, reopening with a reason, and re-planning."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path

from agentqa.api.auth import User, current_user
from agentqa.api.errors import ok
from agentqa.api.routes_projects import store_or_404
from agentqa.api.routes_runs import job_view
from agentqa.api.schemas_gates import ID_MAX, AnswerIn, EmptyIn, Limit, Offset, ReopenIn
from agentqa.orchestrator.gates import changelog, questions
from agentqa.orchestrator.jobs import spawn     # tests replace `spawn` on this module

router = APIRouter(prefix="/projects/{slug}/questions", dependencies=[Depends(current_user)])
QuestionId = Path(ge=1, le=ID_MAX)


@router.get("")
def list_questions(slug: str, status: Literal["open", "answered"] | None = None, limit: int = Limit,
                   offset: int = Offset):
    with store_or_404(slug) as (_, s):
        return ok(questions.listing(s, status, limit, offset))


@router.post("/apply", status_code=202)
def apply_answers(slug: str, body: EmptyIn, user: User = Depends(current_user)):
    with store_or_404(slug) as (p, s):
        job_id = questions.apply(p, s, changelog.who(user), spawn)
        return ok(job_view(s.one("SELECT * FROM jobs WHERE id=?", [job_id])), status=202)


@router.post("/{qid}/answer")
def answer_question(slug: str, body: AnswerIn, qid: int = QuestionId, user: User = Depends(current_user)):
    with store_or_404(slug) as (_, s):
        return ok(questions.answer(s, qid, body.choice, body.value, changelog.who(user)))


@router.post("/{qid}/reopen")
def reopen_question(slug: str, body: ReopenIn, qid: int = QuestionId, user: User = Depends(current_user)):
    with store_or_404(slug) as (_, s):
        return ok(questions.reopen(s, qid, body.why, changelog.who(user)))
