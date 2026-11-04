"""Trim a real No-AI demo store into the small fixture the gate tests load (M1.4).

    python tools/make_gates_fixture.py <demo project folder> [--out tests/fixtures/gates]
                                       [--frontend ../frontend/src/test-fixtures/gates-demo.json]

Run it on a demo copy that stopped at the plan gate and was then continued. It keeps the rows of every gate table
(questions, plan, cases, imported manual cases, defects with evidence, requirements, visual rows, heals) plus what
the plan and the traceability matrix read (rules, documents, segments, the run and its results, trimmed), turns every
path into one relative to the project, and copies at most six small images. Refuses to write anything (exit 1) if a
demo password or one-time code, or an absolute path, is left; only ever replaces a folder that is itself a fixture
(exit 2). It also writes what the API serves for those rows, for the web app's tests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_live_fixture import ABSOLUTE  # noqa: E402

TABLES = {"questions": "id", "plan": "id", "cases": "seq", "manual_cases": "id", "defects": "seq", "requirements": "seq",
          "visual": "key", "heals": "id", "rules": "id", "documents": "id", "segments": "id", "runs": "started_at",
          "results": "rowid"}
META = ("last_run", "workflow_gaps", "production_skipped", "req_dispositions", "triage")
SECRET_KEYS = {"password", "passwd", "pwd", "otp_fixed", "totp_secret"}
MAX_IMAGES, SHOTS, BASELINES = 6, 4, 2
IMAGE_BOX = (360, 640)
MESSAGE_MAX = 300
FIXTURE_FILES = {"rows.json"}
SEVERITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
POSIX_ROOT = re.compile(r"(?<![\w.:/-])/(?:tmp|var|root|opt|srv|mnt|private)/")      # beside ABSOLUTE's /Users and /home
EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
EXAMPLE_DOMAINS = ("example.com", "example.org", "example.net", ".example", ".test", ".invalid", ".localhost")
FILE_SUFFIXES = (".png", ".jpg", ".jpeg", ".json", ".zip", ".webm", ".txt", ".log")


def delivered_codes(project) -> set[str]:
    """The one-time codes the run received: the demo portal's are random and reach AgentQA through the mock inbox,
    which keeps each one (`.agentqa/inbox.db`, `messages.otp`)."""
    path = project.state / "inbox.db"
    if not path.is_file():
        return set()
    with closing(sqlite3.connect(str(path))) as db:
        return {str(r[0]) for r in db.execute("SELECT otp FROM messages WHERE otp IS NOT NULL AND otp != ''")}


def demo_secrets(*configs: Path) -> set[str]:
    """Every password, fixed one-time code and TOTP secret in the demo's settings (and any others given), at any depth."""
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).lower() in SECRET_KEYS and isinstance(value, (str, int)) and str(value):
                    found.add(str(value))
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    for cfg in (ROOT / "demo" / "project.yaml", *configs):
        walk(yaml.safe_load(cfg.read_text(encoding="utf-8")) or {})
    return found


class Relative:
    """Cuts the project folder off every string that names a place inside it."""

    def __init__(self, root: Path):
        base = str(root.resolve())
        self.prefixes = sorted({base, base.replace("\\", "/"), str(root), str(root).replace("\\", "/")}, key=len,
                               reverse=True)

    def text(self, value: str) -> str:
        for prefix in self.prefixes:                          # only at a folder boundary: never "demo" inside "demo2"
            value = re.sub(re.escape(prefix) + r"(?:[\\/]|(?![\w.\-]))", "", value, flags=re.I)
        return value

    def path(self, value: str | None) -> str | None:
        return self.text(value).replace("\\", "/") if value else value

    def walk(self, node):
        if isinstance(node, dict):
            return {k: self.walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [self.walk(v) for v in node]
        return self.text(node) if isinstance(node, str) else node


def read_tables(store) -> dict[str, list[dict]]:
    out = {t: store.all(f"SELECT * FROM {t} ORDER BY {order}") for t, order in TABLES.items()}
    out["results"] = [{**{k: r[k] for k in ("run_id", "case_id", "outcome", "duration", "category", "evidence",
                                                "started_at")}, "message": (r["message"] or "")[:MESSAGE_MAX]}
                      for r in out["results"]]
    return out


def relative_tables(tables: dict[str, list[dict]], rel: Relative) -> dict[str, list[dict]]:
    out = {t: [rel.walk(r) for r in rows] for t, rows in tables.items()}
    for row in out["visual"]:
        for field in ("baseline", "current", "diff"):
            row[field] = rel.path(row.get(field))
    for table in ("defects", "results"):
        for row in out[table]:
            row["evidence"] = [{**e, "path": rel.path(e.get("path"))} if isinstance(e, dict) else e
                               for e in row.get("evidence") or []]
    return out


def choose_images(root: Path, tables: dict[str, list[dict]]) -> list[str]:
    """Relative paths of the images to keep: screenshots of the most severe defects, then two visual baselines."""
    def kept(path) -> bool:
        return isinstance(path, str) and bool(path) and (root / path).is_file()
    defects = sorted(tables["defects"], key=lambda d: (SEVERITY_RANK.get(d["severity"], 9), d["seq"]))
    shots = [e["path"] for d in defects for e in (d["evidence"] or [])[:3]
             if isinstance(e, dict) and e.get("kind") == "screenshot" and kept(e.get("path"))]
    shots = list(dict.fromkeys(shots))[:SHOTS]
    baselines = [v["baseline"] for v in tables["visual"] if kept(v.get("baseline"))]
    return shots + baselines[:BASELINES]


def image_name(rel: str) -> str:
    """The file's own name behind a short fingerprint of its place (two runs can each have a TC-0001.png)."""
    return f"{hashlib.sha1(rel.encode(), usedforsecurity=False).hexdigest()[:6]}-{re.sub(r'[^\w.-]+', '_', Path(rel).name)}"


def shrink(src: Path, dest: Path) -> None:
    from PIL import Image
    with Image.open(src) as img:
        small = img.convert("RGB")
        small.thumbnail(IMAGE_BOX)
        small.convert("P", palette=Image.Palette.ADAPTIVE, colors=64).save(dest, optimize=True)


def _strings(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)
    elif node is not None:
        yield str(node)


def problems(data, secrets: set[str]) -> list[str]:
    """What must not reach git, checked on each value as stored (in JSON text a regex's `\\b` would read as a share)."""
    found = []
    for text in _strings(data):
        found += [f"a demo password or one-time code ({len(s)} characters)" for s in secrets if s in text]
        found += ["an absolute path"] if ABSOLUTE.search(text) or POSIX_ROOT.search(text) else []
        found += ["an email address that is not an example one"] if _real_email(text) else []
    return found


def _real_email(text: str) -> bool:
    """An address outside the reserved example and test domains (file names such as admin@department.png are not)."""
    for match in EMAIL.finditer(text):
        domain = match.group(1).lower()
        if not domain.endswith(EXAMPLE_DOMAINS + FILE_SUFFIXES):
            return True
    return False


def replaceable(out: Path, src: Path) -> bool:
    out, src = out.resolve(), src.resolve()
    if out == src or out.is_relative_to(src) or src.is_relative_to(out):
        return False
    if not out.exists():
        return True
    return out.is_dir() and all((f.is_file() and f.name in FIXTURE_FILES) or
                                (f.is_dir() and f.name == "images" and all(x.suffix == ".png" for x in f.iterdir()))
                                for f in out.iterdir())


def frontend_view(project, store) -> dict:
    """What the API answers for these rows (the web app's tests read it instead of a running server)."""
    from agentqa.orchestrator.gates import changelog, defects, plan, questions, requirements, summary
    return {"gates": summary.counts(project, store), "questions": questions.listing(store, limit=200),
            "plan": plan.overview(store), "cases": plan.cases(store, limit=200),
            "defects": defects.listing(store, limit=200), "requirements": requirements.listing(store, limit=200),
            "changes": changelog.page(store)}


def write(out: Path, src: Path, data: dict, images: list[str]) -> None:
    """The new fixture is made beside the old one and swapped in only when complete: a failure keeps the old one."""
    new = out.with_name(out.name + ".new")
    if new.exists():
        shutil.rmtree(new)
    try:
        (new / "images").mkdir(parents=True)
        for rel in images:
            shrink(src / rel, new / "images" / image_name(rel))
        (new / "rows.json").write_text(json.dumps(data, ensure_ascii=False, indent=0, default=str), encoding="utf-8")
    except BaseException:
        shutil.rmtree(new, ignore_errors=True)
        raise
    if out.exists():
        shutil.rmtree(out)                                    # `replaceable` said it holds a fixture and nothing else
    new.rename(out)


def build(project, store) -> tuple[dict, list[str]]:
    rel = Relative(project.root)
    tables = relative_tables(read_tables(store), rel)
    images = choose_images(project.root, tables)
    meta = {k: rel.walk(store.get_meta(k)) for k in META if store.get_meta(k) is not None}
    data = {"source": "No-AI demo, stopped at the plan gate, then continued (tools/make_gates_fixture.py)",
            "tables": tables, "meta": meta, "files": {r: f"images/{image_name(r)}" for r in images}}
    return data, images


def main(argv: list[str] | None = None) -> int:
    from agentqa.config import Project
    from agentqa.store import Store
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "gates")
    ap.add_argument("--frontend", type=Path, default=ROOT.parent / "frontend" / "src" / "test-fixtures" / "gates-demo.json")
    args = ap.parse_args(argv)
    if not replaceable(args.out, args.project):
        print(f"Refusing to write to {args.out}: it is the project, inside it, or a folder that is not a fixture")
        return 2
    if args.frontend.suffix != ".json" or args.frontend.resolve().is_relative_to(args.project.resolve()):
        print(f"Refusing to write {args.frontend}: the web app's fixture is a .json file outside the project")
        return 2
    project = Project(args.project)
    store = Store(project.db_path)
    try:
        data, images = build(project, store)
        view = Relative(project.root).walk(frontend_view(project, store))
    finally:
        store.close()
    secrets = demo_secrets(project.config_path) | delivered_codes(project)
    found = problems(data, secrets) + problems(view, secrets)
    if found:
        print("Refusing to write the fixture: it contains " + "; ".join(sorted(set(found))))
        return 1
    write(args.out, args.project, data, images)
    args.frontend.parent.mkdir(parents=True, exist_ok=True)
    args.frontend.write_text(json.dumps(view, ensure_ascii=False, indent=0, default=str), encoding="utf-8")
    print(f"{sum(len(v) for v in data['tables'].values())} rows in {len(data['tables'])} tables, {len(images)} images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
