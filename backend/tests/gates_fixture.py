"""Loads the gates fixture (tests/fixtures/gates, made by tools/make_gates_fixture.py) into a project's store, the way
the engine left it: paths absolute inside the project, a few images on disk at their stored places."""
from __future__ import annotations

import copy
import functools
import json
import shutil
from pathlib import Path

from agentqa.config import Project
from agentqa.store import Store

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gates"
PATH_FIELDS = {"visual": ("baseline", "current", "diff")}
EVIDENCE_TABLES = ("defects", "results")


@functools.lru_cache(maxsize=1)
def _rows() -> dict:
    return json.loads((FIXTURE / "rows.json").read_text(encoding="utf-8"))


def rows() -> dict:
    """The fixture as written (a fresh copy: change it freely)."""
    return copy.deepcopy(_rows())


def _absolute(p: Project, rel: str | None) -> str | None:
    return str(p.root / rel) if rel else rel


def _placed(p: Project, table: str, row: dict) -> dict:
    out = dict(row)
    for field in PATH_FIELDS.get(table, ()):
        out[field] = _absolute(p, out.get(field))
    if table in EVIDENCE_TABLES and out.get("evidence"):
        out["evidence"] = [{**e, "path": _absolute(p, e.get("path"))} for e in out["evidence"]]
    return out


def load(p: Project, s: Store) -> dict[str, int]:
    """Insert every fixture row into `s` and copy the images into `p`; returns the row count per table."""
    data = rows()
    for table, items in data["tables"].items():
        for row in items:
            s.insert(table, _placed(p, table, row))
    for key, value in data["meta"].items():
        s.set_meta(key, value)
    for rel, image in data["files"].items():
        dest = p.root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURE / image, dest)
    return {table: len(items) for table, items in data["tables"].items()}
