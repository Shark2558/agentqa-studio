"""Gate 2 — the test plan (M1.4): overview, cases, decisions per case / type / imported case, approval, Excel."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response

from agentqa.api.auth import User, current_user, download_origin_check
from agentqa.api.errors import ok
from agentqa.api.routes_projects import store_or_404
from agentqa.api.schemas_gates import (CASE_TYPE, ApproveIn, CaseDecisionIn, ImportedDecisionIn, Limit, Offset,
                                       TypeDecisionIn)
from agentqa.orchestrator.gates import changelog, plan

router = APIRouter(prefix="/projects/{slug}/plan", dependencies=[Depends(current_user)])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NO_STORE = {"Cache-Control": "no-store"}
CaseStatus = Literal["proposed", "approved", "rejected"]


def attachment(data: bytes, name: str, media_type: str) -> Response:
    """A download; `name` is plain ASCII (gates.exports.download_name)."""
    return Response(data, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{name}"',
                                                          **NO_STORE})


@router.get("")
def get_plan(slug: str):
    with store_or_404(slug) as (_, s):
        return ok(plan.overview(s))


@router.get("/cases")
def list_cases(slug: str, ctype: str | None = Query(default=None, alias="type", pattern=CASE_TYPE),
               status: CaseStatus | None = None, limit: int = Limit, offset: int = Offset):
    with store_or_404(slug) as (_, s):
        return ok(plan.cases(s, ctype, status, limit, offset))


@router.post("/cases")
def decide_cases(slug: str, body: CaseDecisionIn, user: User = Depends(current_user)):
    with store_or_404(slug) as (_, s):
        return ok(plan.decide_cases(s, body.ids, body.decision, body.why, changelog.who(user)))


@router.post("/types/{ctype}")
def decide_type(slug: str, body: TypeDecisionIn, ctype: str = Path(pattern=CASE_TYPE),
                user: User = Depends(current_user)):
    with store_or_404(slug) as (_, s):
        return ok(plan.decide_type(s, ctype, body.decision, body.why, changelog.who(user)))


@router.post("/imported")
def decide_imported(slug: str, body: ImportedDecisionIn, user: User = Depends(current_user)):
    with store_or_404(slug) as (_, s):
        return ok(plan.decide_imported(s, body.ids, body.decision, body.why, changelog.who(user)))


@router.post("/approve")
def approve_plan(slug: str, body: ApproveIn, user: User = Depends(current_user)):
    with store_or_404(slug) as (_, s):
        return ok(plan.approve(s, body.digest, body.why, changelog.who(user)))


@router.get("/testcases.xlsx", dependencies=[Depends(download_origin_check)])
def test_cases_workbook(slug: str, user: User = Depends(current_user)):
    with store_or_404(slug) as (p, s):
        data, name = plan.workbook(p, s, changelog.who(user))
    return attachment(data, name, XLSX)
