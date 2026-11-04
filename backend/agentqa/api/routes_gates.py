"""Requirements (FR-ONB-4), the change log (FR-ACC-3) and what is waiting for a person (M1.4)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from agentqa.api.auth import User, current_user, download_origin_check
from agentqa.api.errors import ok
from agentqa.api.routes_plan import XLSX, attachment
from agentqa.api.routes_projects import store_or_404
from agentqa.api.schemas_gates import DOC_ID, ID_MAX, LIST_MAX, DispositionIn, Offset
from agentqa.orchestrator.gates import changelog, requirements, summary

router = APIRouter(prefix="/projects/{slug}", dependencies=[Depends(current_user)])


@router.get("/requirements")
def list_requirements(slug: str, limit: int = Query(default=LIST_MAX, ge=1, le=LIST_MAX), offset: int = Offset):
    with store_or_404(slug) as (_, s):
        return ok(requirements.listing(s, limit, offset))


@router.get("/requirements/rtm.xlsx", dependencies=[Depends(download_origin_check)])
def rtm_workbook(slug: str, user: User = Depends(current_user)):
    with store_or_404(slug) as (p, s):
        data, name = requirements.rtm(p, s, changelog.who(user))
    return attachment(data, name, XLSX)


@router.patch("/requirements/{rid:path}")            # ids come from documents as written: "BR/01" is one
def set_disposition(slug: str, body: DispositionIn, rid: str = Path(pattern=DOC_ID),
                    user: User = Depends(current_user)):
    with store_or_404(slug) as (_, s):
        return ok(requirements.set_disposition(s, rid, body.disposition, body.why, changelog.who(user)))


@router.get("/changes")
def list_changes(slug: str, limit: int = Query(default=changelog.PAGE_DEFAULT, ge=1, le=changelog.PAGE_MAX),
                 before: int | None = Query(default=None, ge=1, le=ID_MAX)):
    with store_or_404(slug) as (_, s):
        return ok(changelog.page(s, limit, before))


@router.get("/gates")
def gate_counts(slug: str):
    with store_or_404(slug) as (p, s):
        return ok(summary.counts(p, s))
