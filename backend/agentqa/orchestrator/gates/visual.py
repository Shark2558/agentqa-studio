"""Visual review (M1.4 Phase C): approve a changed screen as its new baseline, or report it as a defect.

`approve_row` and `report_row` are the old dashboard's code moved here, not rewritten (web/app.py calls them too). What
is new: the current image is copied only when it is a file of the project's own (the `files` guard) and the key is a
plain name, a refusal while a run goes, a reason to accept a change (decision 4), and the change log."""
from __future__ import annotations

import re
import shutil
import threading
from typing import Any

from agentqa.config import Project
from agentqa.orchestrator import Busy
from agentqa.orchestrator.gates import GateError, changelog, files, need_why, run_going
from agentqa.store import Store, now

KEY = r"^[\w@.\-]{1,200}$"
IMAGES = ("baseline", "current", "diff")
_DECIDING = threading.Lock()          # one decision at a time: a double-click cannot act twice
ORDER = "(status!='changed'), path, role"
FIELDS = ("key", "role", "path", "status", "diff_ratio", "run_id", "case_id", "updated_at")


def _plain_key(key: object) -> bool:
    return isinstance(key, str) and re.fullmatch(KEY, key) is not None


def item(project: Project, v: dict) -> dict[str, Any]:
    """A screen as the page shows it: never a path, only which of its three images can be shown."""
    return {**{k: v.get(k) for k in FIELDS}, "images": {w: image(project, v, w) is not None for w in IMAGES}}


def image(project: Project, v: dict, which: str) -> files.SafeFile | None:
    found = files.safe_file(project, v.get(which)) if which in IMAGES else None
    return found if found and found.inline else None


def picture(project: Project, store: Store, key: str, which: str) -> files.SafeFile:
    v = store.one("SELECT * FROM visual WHERE key=?", [key])
    found = image(project, v, which) if v else None
    if found is None:
        raise GateError(404, "not_found", "No such picture")
    return found


def listing(project: Project, store: Store, show: str = "changed", limit: int = 50, offset: int = 0) -> dict[str, Any]:
    where, params = ("", []) if show == "all" else ("WHERE status=?", [show])
    rows = store.all(f"SELECT * FROM visual {where} ORDER BY {ORDER} LIMIT ? OFFSET ?", [*params, limit, offset])
    counts = {r["status"]: r["n"] for r in store.all("SELECT status, COUNT(*) n FROM visual GROUP BY status")}
    return {"items": [item(project, v) for v in rows], "counts": counts,
            "total": store.scalar(f"SELECT COUNT(*) FROM visual {where}", params) or 0}


def approve_row(project: Project, store: Store, v: dict) -> bool:
    """The current image becomes the baseline (and its layout image, when there is one). False, with nothing copied,
    when the key is not a plain name or the current image is not a picture inside the project's result folders."""
    current = image(project, v, "current")
    if current is None or not _plain_key(v.get("key")):
        return False
    base = project.root / "visual" / "baselines"
    base.mkdir(parents=True, exist_ok=True)
    layout = files.safe_file(project, str(current.path.with_name(current.path.name.replace("-current.png", "-layout.png"))))
    shutil.copy(current.path, base / f"{v['key']}.png")
    if layout is not None:
        shutil.copy(layout.path, base / f"{v['key']}-layout.png")
    store.update("visual", "key", v["key"], {"status": "approved", "baseline": str(base / f"{v['key']}.png"),
                                             "updated_at": now()})
    return True


def report_row(project: Project, store: Store, v: dict) -> str:
    """A draft defect for the change (the same one again if it was reported before); returns its id."""
    key = v["key"]
    sig = f"visual:{key}"
    old = store.one("SELECT * FROM defects WHERE signature=?", [sig])
    evidence = [{"kind": "difference", "role": v["role"], "path": v["diff"] or v["current"]},
                {"kind": "screenshot", "role": v["role"], "path": v["current"]}]
    row = {"run_id": v["run_id"], "case_ids": [v["case_id"]] if v["case_id"] else [], "signature": sig,
           "title": f"Unexpected visual change on {v['path']} ({v['role']})", "severity": "Medium", "priority": "P2",
           "role": v["role"], "url": project.url(v["path"]),
           "steps": f"Log in as {v['role']}.\nOpen {project.url(v['path'])}.\nCompare with the approved snapshot.",
           "expected": "The screen looks like its approved snapshot.",
           "actual": f"{(v['diff_ratio'] or 0):.2%} of the layout differs from the approved snapshot.",
           "evidence": evidence, "rule_ids": [], "req_ids": []}
    if old:
        store.update("defects", "id", old["id"], {**row, "status": "draft"})
        did = old["id"]
    else:
        seq = (store.scalar("SELECT MAX(seq) FROM defects") or 0) + 1
        did = f"DEF-{seq:03d}"
        store.insert("defects", {"id": did, "seq": seq, **row, "status": "draft", "created_at": now(),
                                 "notes": "Reported from Visual review.", "external_key": None})
    store.update("visual", "key", key, {"status": "reported", "updated_at": now()})
    return did


def _not_running(project: Project, store: Store) -> None:
    """A run writes baselines and visual rows of its own: a decision waits until it ends."""
    if run_going(project, store):
        raise Busy("A run is going: decide on screens once it has finished.")


def _approved(project: Project, store: Store, v: dict) -> bool:
    try:
        return approve_row(project, store, v)
    except OSError as exc:
        raise GateError(503, "file_error", f"Could not copy the picture just now ({exc.__class__.__name__}); "
                                           "try again") from exc


def _changed(store: Store, key: str) -> dict:
    v = store.one("SELECT * FROM visual WHERE key=?", [key])
    if not v:
        raise GateError(404, "not_found", "No such screen")
    if v["status"] != "changed":
        raise GateError(409, "not_changed", "This screen is not waiting for a decision")
    return v


def decide(project: Project, store: Store, key: str, decision: str, why: str, by: str) -> dict[str, Any]:
    need_why(decision == "approve", why)          # accepting a change as the new normal needs a reason (decision 4)
    with _DECIDING:
        _not_running(project, store)
        v = _changed(store, key)
        if decision == "approve":
            if not _approved(project, store, v):
                raise GateError(409, "no_image", "This screen has no current picture to keep as its baseline")
            changelog.record(store, "visual", key, "approved as the new baseline", why, by)
            return {"key": key, "status": "approved"}
        did = report_row(project, store, v)
        changelog.record(store, "visual", key, f"reported as {did}", why, by)
        return {"key": key, "status": "reported", "defect": did}


def _named(store: Store, rows: list[dict], keys: list[str] | None) -> list[dict]:
    if not keys:
        return rows
    wanted = list(dict.fromkeys(keys))
    known = {r["key"] for r in store.all(f"SELECT key FROM visual WHERE key IN ({','.join('?' * len(wanted))})", wanted)}
    unknown = [k for k in wanted if k not in known]
    if unknown:
        raise GateError(422, "validation", f"keys: no such screen: {', '.join(unknown[:5])}")
    return [r for r in rows if r["key"] in set(wanted)]


def approve_all(project: Project, store: Store, keys: list[str] | None, why: str, by: str) -> dict[str, int]:
    """Every changed screen named (or every changed screen) becomes its baseline; one change-log row for them all,
    written even when a copy fails part-way, for the screens already approved."""
    need_why(True, why)
    with _DECIDING:
        _not_running(project, store)
        rows = _named(store, store.all(f"SELECT * FROM visual WHERE status='changed' ORDER BY {ORDER}"), keys)
        approved = 0
        try:
            for v in rows:
                approved += _approved(project, store, v)
        finally:
            if approved:
                changelog.record(store, "visual", "-", f"approved {approved} changed screen(s) as the new baselines",
                                 why, by)
        return {"approved": approved, "skipped": len(rows) - approved}
