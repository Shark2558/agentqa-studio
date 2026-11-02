"""Projects on disk: one folder per application under the projects directory."""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path

from agentqa import readiness
from agentqa.config import Project, init_project
from agentqa.orchestrator import Conflict, NotFound
from agentqa.store import Store

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent.parent
SLUG_MAX = 40
URL_RE = re.compile(r"^https?://[^\s/]+")


def projects_dir() -> Path:
    d = Path(os.environ.get("AGENTQA_PROJECTS", ROOT / "projects")).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def slug_for(name: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")[:SLUG_MAX] or "project"


def open_project(slug: str) -> tuple[Project, Store]:
    base = projects_dir()
    d = (base / slug).resolve()
    if d.parent != base or not (d / "project.yaml").exists():
        raise NotFound("No such project")
    p = Project(d)
    return p, Store(p.db_path)


def summary(d: Path) -> dict:
    """One row for the projects list: counts, last run and readiness when a run exists."""
    try:
        p = Project(d)
        row = {"slug": d.name, "name": p.name, "url": p.base_url}
        if p.db_path.exists():
            st = Store(p.db_path)
            run = st.one("SELECT * FROM runs WHERE status='done' ORDER BY started_at DESC LIMIT 1")
            row.update(cases=st.scalar("SELECT COUNT(*) FROM cases"),
                       defects=st.scalar("SELECT COUNT(*) FROM defects WHERE status NOT IN ('rejected','resolved')"),
                       last=(run["started_at"][:16].replace("T", " ") if run else None))
            if run:
                r = readiness.compute(p, st)
                row.update(score=r["score"], verdict=r["verdict"])
        return row
    except Exception:  # noqa: BLE001 - one broken project must not hide the others
        log.exception("project %s cannot be read", d.name)          # the detail (paths included) goes to the log only
        return {"slug": d.name, "name": d.name, "url": "configuration error"}


def list_projects() -> list[dict]:
    return [summary(d) for d in sorted(projects_dir().iterdir()) if (d / "project.yaml").exists()]


def create_project(name: str, url: str) -> tuple[str, bool]:
    """(slug, created). The same project asked for twice is returned with created=False; the same slug for a
    different application is a Conflict (the caller chooses another name)."""
    name, url = name.strip(), url.strip()
    if not name:
        raise ValueError("Give the project a name")
    if not URL_RE.match(url):
        raise ValueError("The portal address must be a full URL starting with http:// or https://")
    slug = slug_for(name)
    if (projects_dir() / slug / "project.yaml").exists():
        if Project(projects_dir() / slug).base_url.rstrip("/") != url.rstrip("/"):
            raise Conflict(f"A project named '{slug}' already exists for another address; choose another name")
        return slug, False
    init_project(projects_dir() / slug, name, url)
    return slug, True


def create_demo() -> str:
    """Copy the bundled demo project (SRS, settings, manual test sheet) into the projects directory."""
    dest = projects_dir() / "demo"
    dest.mkdir(exist_ok=True)
    (dest / "srs").mkdir(exist_ok=True)
    shutil.copy(ROOT / "demo" / "project.yaml", dest / "project.yaml")
    for f in (ROOT / "demo" / "srs").glob("*.docx"):
        shutil.copy(f, dest / "srs" / f.name)
    (dest / "imports").mkdir(exist_ok=True)
    if (ROOT / "demo" / "manual_tests.xlsx").exists():
        shutil.copy(ROOT / "demo" / "manual_tests.xlsx", dest / "imports" / "manual_tests.xlsx")
    return "demo"
