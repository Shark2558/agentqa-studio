"""Gate 3 — defects (M1.4): the list, decisions, the Jira-style and Zoho CSV downloads, and evidence by index."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import FileResponse, Response

from agentqa.api.auth import User, current_user, download_origin_check
from agentqa.api.errors import ok
from agentqa.api.routes_plan import NO_STORE, attachment
from agentqa.api.routes_projects import store_or_404
from agentqa.api.schemas_gates import DEFECT_ID, DefectDecisionIn, Limit, Offset
from agentqa.orchestrator.gates import changelog, defects, exports

router = APIRouter(prefix="/projects/{slug}/defects", dependencies=[Depends(current_user)])
Status = Literal["draft", "confirmed", "exported", "rejected", "resolved", "fixed", "reopened"]
Severity = Literal["Critical", "High", "Medium", "Low"]
Drafts = Query(default=0, ge=0, le=1)
EVIDENCE_MAX = 1000


@router.get("")
def list_defects(slug: str, status: Status | None = None, severity: Severity | None = None, limit: int = Limit,
                 offset: int = Offset):
    with store_or_404(slug) as (_, s):
        return ok(defects.listing(s, status, severity, limit, offset))


@router.post("/decisions")
def decide(slug: str, body: DefectDecisionIn, user: User = Depends(current_user)):
    with store_or_404(slug) as (_, s):
        return ok(defects.decide(s, body.ids, body.decision, body.why, changelog.who(user)))


def _csv(slug: str, kind: Literal["jira", "zoho"], drafts: int, user: User) -> Response:
    with store_or_404(slug) as (p, s):
        data, name = defects.export(p, s, kind, bool(drafts), changelog.who(user))
    return attachment(data, exports.download_name(slug, name), "text/csv; charset=utf-8")


@router.get("/export.csv", dependencies=[Depends(download_origin_check)])
def export_csv(slug: str, drafts: int = Drafts, user: User = Depends(current_user)):
    return _csv(slug, "jira", drafts, user)


@router.get("/zoho.csv", dependencies=[Depends(download_origin_check)])
def export_zoho(slug: str, drafts: int = Drafts, user: User = Depends(current_user)):
    return _csv(slug, "zoho", drafts, user)


@router.get("/{did}/evidence/{n}", dependencies=[Depends(download_origin_check)])   # no probing from the tested site
def get_evidence(slug: str, did: str = Path(pattern=DEFECT_ID), n: int = Path(ge=0, le=EVIDENCE_MAX)):
    with store_or_404(slug) as (p, s):
        found = defects.evidence(p, s, did, n)
    if found.inline:
        return FileResponse(found.path, media_type=found.media_type, headers=NO_STORE)
    return FileResponse(found.path, media_type=found.media_type, filename=found.path.name, headers=NO_STORE)
