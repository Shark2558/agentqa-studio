from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, Depends

from agentqa.api.auth import current_user
from agentqa.api.errors import ApiError, ok
from agentqa.api.schemas import ProjectIn
from agentqa.config import Project
from agentqa.orchestrator import Busy, Conflict, NotFound, projects
from agentqa.orchestrator.gates import GateError
from agentqa.store import Store

router = APIRouter(prefix="/projects", dependencies=[Depends(current_user)])


def project_or_404(slug: str) -> Project:
    """The project, without opening its store (for routes that only need its settings or folders)."""
    try:
        return projects.find_project(slug)
    except NotFound as exc:
        raise ApiError(404, "not_found", str(exc)) from exc


@contextmanager
def store_or_404(slug: str) -> Iterator[tuple[Project, Store]]:
    """The project and its store for this request, closed when the block ends (M1.3 #16). What the block refuses
    becomes the answer: no such project (or thing inside it) 404, a gate's refusal its own status, a running job 409."""
    try:
        with projects.project_store(slug) as pair:
            yield pair
    except NotFound as exc:
        raise ApiError(404, "not_found", str(exc)) from exc
    except GateError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from exc
    except Busy as exc:
        raise ApiError(409, "busy", str(exc)) from exc


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
    p = projects.find_project(slug)
    if created:
        from agentqa.orchestrator import intake
        intake.set_environment(p, body.environment)
    return ok(projects.summary(p.root), status=201 if created else 200)


@router.post("/demo", status_code=201)
def create_demo():
    existed = (projects.projects_dir() / "demo" / "project.yaml").exists()
    slug = projects.create_demo()
    p = projects.find_project(slug)
    return ok(projects.summary(p.root), status=200 if existed else 201)


@router.get("/{slug}")
def get_project(slug: str):
    return ok(projects.summary(project_or_404(slug).root))
