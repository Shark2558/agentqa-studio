"""The onboarding wizard's endpoints: documents, typed requirements, accounts and preflight (the requirements list
moved to routes_gates in M1.4)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, UploadFile
from starlette.concurrency import run_in_threadpool

from agentqa.api.auth import current_user
from agentqa.api.errors import ApiError, ok
from agentqa.api.routes_projects import project_or_404, store_or_404
from agentqa.api.schemas import AccountsIn, PreflightIn, TypedIn
from agentqa.orchestrator import NotFound, intake, preflight

router = APIRouter(prefix="/projects/{slug}", dependencies=[Depends(current_user)])
tools = APIRouter(dependencies=[Depends(current_user)])
CHUNK = 1024 * 1024


async def _read_limited(up: UploadFile) -> bytes:
    """The whole upload, or TooLarge as soon as it passes the cap (never buffering more than that)."""
    parts, total = [], 0
    while chunk := await up.read(CHUNK):
        total += len(chunk)
        if total > intake.MAX_UPLOAD:
            raise intake.TooLarge(f"{up.filename} is larger than {intake.MAX_UPLOAD // (1024 * 1024)} MB")
        parts.append(chunk)
    return b"".join(parts)


async def _store_all(slug: str, files: list[UploadFile], folder: str):
    """Every file is checked (name, size) before any is written, so one bad file refuses the whole batch and
    nothing half-done is left behind; the readers then run in a worker thread, never on the event loop."""
    p = project_or_404(slug)
    refused = []
    for up in files:
        try:
            intake.safe_name(up.filename or "")
        except intake.Unsupported as exc:
            refused.append(str(exc))
    if refused:
        raise ApiError(422, "validation", "; ".join(refused))
    try:
        payloads = [(up.filename or "", await _read_limited(up)) for up in files]
        out = [await run_in_threadpool(intake.save_document, p, name, data, folder) for name, data in payloads]
    except intake.TooLarge as exc:
        raise ApiError(413, "too_large", str(exc)) from exc
    return ok(out, status=201)


@tools.post("/preflight")
async def run_preflight(body: PreflightIn):
    try:
        return ok(await run_in_threadpool(preflight.check, body.url))
    except ValueError as exc:
        raise ApiError(422, "validation", str(exc)) from exc


@router.get("/documents")
def list_documents(slug: str):
    with store_or_404(slug) as (p, s):
        return ok(intake.list_documents(p, s))


@router.post("/documents", status_code=201)
async def upload_documents(slug: str, files: list[UploadFile]):
    return await _store_all(slug, files, "srs")


@router.post("/imports", status_code=201)
async def upload_imports(slug: str, files: list[UploadFile]):
    return await _store_all(slug, files, "imports")


@router.delete("/documents/{name:path}")
def delete_document(slug: str, name: str):
    p = project_or_404(slug)
    try:
        intake.delete_document(p, name)
    except NotFound as exc:
        raise ApiError(404, "not_found", str(exc)) from exc
    return ok({"deleted": name})


@router.post("/requirements/typed")
def typed_requirements(slug: str, body: TypedIn):
    from agentqa.agents import req_chat
    p = project_or_404(slug)
    intake.save_typed(p, body.text, [a.model_dump() for a in body.answers], items=body.items)
    return ok(req_chat.chat(p, body.text))


@router.get("/accounts")
def get_accounts(slug: str):
    return ok(intake.accounts_view(project_or_404(slug)))


@router.put("/accounts")
def put_accounts(slug: str, body: AccountsIn):
    p = project_or_404(slug)
    try:
        intake.save_accounts(p, [r.model_dump(exclude_none=True) for r in body.roles], no_login=body.no_login)
    except ValueError as exc:
        raise ApiError(422, "validation", str(exc)) from exc
    return ok(intake.accounts_view(project_or_404(slug)))   # project.yaml changed: answer from a re-read
