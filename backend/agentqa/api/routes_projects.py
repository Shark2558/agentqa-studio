from __future__ import annotations

from fastapi import APIRouter, Depends

from agentqa.api.auth import current_user
from agentqa.api.errors import ApiError, ok
from agentqa.api.schemas import ProjectIn
from agentqa.orchestrator import Conflict, NotFound, projects

router = APIRouter(prefix="/projects", dependencies=[Depends(current_user)])


def open_or_404(slug: str):
    try:
        return projects.open_project(slug)
    except NotFound as exc:
        raise ApiError(404, "not_found", str(exc)) from exc


@router.get("")
def list_projects():
    return ok(projects.list_projects())


@router.post("", status_code=201)
def create_project(body: ProjectIn):
    try:
        slug, created = projects.create_project(body.name, body.url)
    except Conflict as exc:
        raise ApiError(409, "conflict", str(exc)) from exc
    except ValueError as exc:
        raise ApiError(422, "validation", str(exc)) from exc
    p, _ = projects.open_project(slug)
    return ok(projects.summary(p.root), status=201 if created else 200)


@router.post("/demo", status_code=201)
def create_demo():
    existed = (projects.projects_dir() / "demo" / "project.yaml").exists()
    slug = projects.create_demo()
    p, _ = projects.open_project(slug)
    return ok(projects.summary(p.root), status=200 if existed else 201)


@router.get("/{slug}")
def get_project(slug: str):
    p, _ = open_or_404(slug)
    return ok(projects.summary(p.root))
