"""The help box, take-over, pause and the teach routes (M1.4 Phase C).

`GET /assist` is polled by every open page, so it reads with one bare query and never opens the full store. A person
who may only watch sees who is waiting, not the screen: the list leaves the screen's parts out and the screenshot
answers 403."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import FileResponse

from agentqa.api.auth import WRITE_ROLES, User, current_user, download_origin_check
from agentqa.api.errors import ApiError, ok
from agentqa.api.routes_plan import NO_STORE
from agentqa.api.routes_projects import project_or_404, store_or_404
from agentqa.api.routes_runs import job_view
from agentqa.api.schemas_gates import ID_MAX, EmptyIn
from agentqa.api.schemas_review import ROLE, AssistAnswerIn, CommandIn, TeachIn
from agentqa.orchestrator.gates import GateError, changelog, helpbox
from agentqa.orchestrator.jobs import spawn     # tests replace `spawn` on this module

router = APIRouter(prefix="/projects/{slug}", dependencies=[Depends(current_user)])
AssistId = Path(ge=1, le=ID_MAX)


@router.get("/assist")
def list_assist(slug: str, user: User = Depends(current_user)):
    try:
        return ok(helpbox.pending(project_or_404(slug), user.role in WRITE_ROLES))
    except GateError as exc:                             # 503 while the database cannot be read
        raise ApiError(exc.status, exc.code, exc.message) from exc


@router.post("/assist/{aid}/answer")
def answer(slug: str, body: AssistAnswerIn, aid: int = AssistId, user: User = Depends(current_user)):
    with store_or_404(slug) as (_, s):
        return ok(helpbox.answer(s, aid, body.answer(), changelog.who(user)))


@router.post("/assist/{aid}/commands", status_code=202)
def command(slug: str, body: CommandIn, aid: int = AssistId, user: User = Depends(current_user)):
    with store_or_404(slug) as (p, s):
        return ok(helpbox.command(p, s, aid, body.model_dump(), changelog.who(user)), status=202)


@router.get("/assist/{aid}/shot", dependencies=[Depends(download_origin_check)])
def shot(slug: str, aid: int = AssistId, v: int = Query(default=0, ge=0, le=ID_MAX),
         user: User = Depends(current_user)):
    """`v` only makes each new screenshot a new address for the browser; the file is never cached."""
    if user.role not in WRITE_ROLES:
        raise ApiError(403, "read_only", "Only the owner or a tester sees the agent's screen")
    try:
        found = helpbox.shot(project_or_404(slug), aid)
    except GateError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from exc
    return FileResponse(found.path, media_type=found.media_type, headers=NO_STORE)


@router.post("/pause")
def pause(slug: str, body: EmptyIn, user: User = Depends(current_user)):
    with store_or_404(slug) as (p, s):
        return ok(helpbox.pause(p, s, changelog.who(user)))


@router.post("/resume")
def resume(slug: str, body: EmptyIn, user: User = Depends(current_user)):
    with store_or_404(slug) as (p, s):
        return ok(helpbox.resume(p, s, changelog.who(user)))


def _teach(slug: str, args: list[str], label: str, role: str) -> dict:
    """A job with a visible browser where the person shows AgentQA the way (a login, or around the site)."""
    with store_or_404(slug) as (p, s):
        helpbox.teach_role(p, role)
        job_id = spawn(p, s, [*args, "--role", role], label, headed=True)       # Busy answers 409
        return ok(job_view(s.one("SELECT * FROM jobs WHERE id=?", [job_id])), status=202)


@router.post("/accounts/{role}/teach", status_code=202)
def teach_login(slug: str, body: EmptyIn, role: str = Path(pattern=ROLE)):
    return _teach(slug, ["teach-login"], f"teach-{role}", role)


@router.post("/explore/teach", status_code=202)
def teach_nav(slug: str, body: TeachIn):
    return _teach(slug, ["teach-nav"], f"teach-nav-{body.role}", body.role)
