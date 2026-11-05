"""Visual review and heals (M1.4 Phase C): changed screens approved as baselines or reported, the Healer's fixes
approved or rejected. Pictures go by key and which one, never by path."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path
from fastapi.responses import FileResponse

from agentqa.api.auth import User, current_user, download_origin_check
from agentqa.api.errors import ok
from agentqa.api.routes_plan import NO_STORE
from agentqa.api.routes_projects import store_or_404
from agentqa.api.schemas_gates import ID_MAX, Limit, Offset
from agentqa.api.schemas_review import VISUAL_KEY, HealDecisionIn, VisualApproveAllIn, VisualDecisionIn
from agentqa.orchestrator.gates import changelog, heals, visual

router = APIRouter(prefix="/projects/{slug}", dependencies=[Depends(current_user)])
Show = Literal["changed", "all", "approved", "reported", "baseline", "same"]
Which = Literal["baseline", "current", "diff"]
HealStatus = Literal["proposed", "approved", "rejected"]
KeyParam = Path(pattern=VISUAL_KEY)


@router.get("/visual")
def list_visual(slug: str, show: Show = "changed", limit: int = Limit, offset: int = Offset):
    with store_or_404(slug) as (p, s):
        return ok(visual.listing(p, s, show, limit, offset))


@router.post("/visual/approve-all")                   # registered before /visual/{key}
def approve_all(slug: str, body: VisualApproveAllIn, user: User = Depends(current_user)):
    with store_or_404(slug) as (p, s):
        return ok(visual.approve_all(p, s, body.keys, body.why, changelog.who(user)))


@router.get("/visual/{key}/{which}", dependencies=[Depends(download_origin_check)])   # no probing from the tested site
def visual_picture(slug: str, which: Which, key: str = KeyParam):
    with store_or_404(slug) as (p, s):
        found = visual.picture(p, s, key, which)
    return FileResponse(found.path, media_type=found.media_type, headers=NO_STORE)


@router.post("/visual/{key}")
def decide_visual(slug: str, body: VisualDecisionIn, key: str = KeyParam, user: User = Depends(current_user)):
    with store_or_404(slug) as (p, s):
        return ok(visual.decide(p, s, key, body.decision, body.why, changelog.who(user)))


@router.get("/heals")
def list_heals(slug: str, status: HealStatus | None = None, limit: int = Limit, offset: int = Offset):
    with store_or_404(slug) as (_, s):
        return ok(heals.listing(s, status, limit, offset))


@router.post("/heals/{hid}")
def decide_heal(slug: str, body: HealDecisionIn, hid: int = Path(ge=1, le=ID_MAX), user: User = Depends(current_user)):
    with store_or_404(slug) as (p, s):
        return ok(heals.decide(p, s, hid, body.decision, body.why, changelog.who(user)))
