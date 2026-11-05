"""Healer agent: repairs tests broken by UI changes, never their expectations.

When a test fails because a field is no longer found (a test issue, not a
defect), the Healer looks up what that field was (its label and type from the
last exploration), re-reads the page, finds the closest field now present and
proposes one locator change per screen for review. It never touches expected
values, so a heal cannot turn a real failure into a pass.
"""
from __future__ import annotations

import json
import re

from agentqa.agents.explorer import probe_page
from agentqa import live
from agentqa.config import Project
from agentqa.store import Store, now
from agentqa.util import similarity


def _old_field(store: Store, path: str, name: str) -> dict:
    for s in store.all("SELECT forms FROM screens WHERE path=?", [path]):
        for form in s["forms"] or []:
            for f in form["fields"]:
                if f["name"] == name:
                    return f
    return {"name": name, "label": name.replace("_", " "), "type": ""}


def heal(project: Project, store: Store, run_id: str | None = None) -> dict:
    run_id = run_id or store.get_meta("last_run")
    store.exec("DELETE FROM heals WHERE status='proposed'")
    issues = store.all("SELECT * FROM results WHERE run_id=? AND category IN ('test-issue', 'environment')", [run_id])
    groups: dict[tuple, dict] = {}
    manual = 0
    for res in issues:
        case = store.one("SELECT * FROM cases WHERE id=?", [res["case_id"]])
        if not case:
            continue
        msg = res["message"] or ""
        mh = re.search(r"\[heal (\{.*\})\]", msg)
        if mh and case["type"] == "workflow":
            h = json.loads(mh.group(1))
            wf = (case["params"] or {}).get("workflow_id")
            reason = (f"Workflow {wf}, step {h['step']}: the control '{h['old'][5:] if h['old'].startswith('text=') else h['old']}' "
                      f"is gone, but the same record now offers '{h['offered']}'. Approving changes the step to "
                      f"'{h['new']}' in project.yaml. Expected results are unchanged.")
            live.emit("healer", "heal", reason, old=h["old"], new=h["new"], level="ok")
            store.insert("heals", {"case_id": case["id"], "run_id": run_id, "kind": "workflow",
                                   "old": {"workflow": wf, "step": h["step"], "key": h["key"], "value": h["old"]},
                                   "new": {"value": h["new"], "offered": h["offered"]}, "reason": reason,
                                   "status": "proposed", "created_at": now()})
            continue
        m = re.search(r"field '([^']+)' not found", msg)
        if res["category"] == "environment" or not m:
            store.insert("heals", {"case_id": case["id"], "run_id": run_id, "kind": "manual",
                                   "old": {"message": msg[:400]}, "new": None,
                                   "reason": ("The application was unreachable; check the test environment."
                                              if res["category"] == "environment" else
                                              "Not a missing-locator problem; review this test manually."),
                                   "status": "proposed", "created_at": now()})
            manual += 1
            continue
        missing = m.group(1)
        path, role = case["path"], case["role"]
        if case["type"] == "workflow":
            for st in (case["params"] or {}).get("steps", []):
                if missing in (st.get("fill") or {}):
                    path, role = st.get("goto") or path, st["role"]
                    break
        g = groups.setdefault((path, missing), {"cases": [], "role": role, "workflow": False})
        g["cases"].append(case["id"])
        g["workflow"] = g["workflow"] or case["type"] == "workflow"

    proposed = 0
    live.emit("healer", "start", f"{len(issues)} test issue(s) to examine; {len(groups)} missing field(s)")
    for (path, missing), g in groups.items():
        old = _old_field(store, path, missing)
        live.emit("healer", "observe", f"Re-reading {path} as {g['role']} to find what replaced '{missing}'", path=path,
                  role=g["role"])
        info = probe_page(project, g["role"], path) if path else None
        best, score = None, 0.0
        present = set()
        for form in (info or {}).get("forms", []):
            for f in form["fields"]:
                present.add(f["name"])
        for form in (info or {}).get("forms", []):
            for f in form["fields"]:
                if f["name"] == missing:
                    continue
                s = max(similarity(old.get("label"), f.get("label")), 0.8 * similarity(missing, f.get("name")))
                if old.get("type") and f.get("type") and old["type"] != f["type"]:
                    s -= 0.25
                if s > score:
                    best, score = f, s
        if missing in present:
            reason, kind, new = (f"'{missing}' is present again on {path}; re-run the tests.", "manual", None)
        elif not best or score < 0.6:
            reason, kind, new = (f"No field like '{old.get('label')}' remains on {path}. The field may have been "
                                 f"removed, which could be a defect; review manually.", "manual", None)
        else:
            new = {"field": best["name"], "label": best["label"]}
            kind = "locator"
            reason = (f"On {path}, field '{missing}' (label '{old.get('label')}') is gone; '{best['name']}' "
                      f"(label '{best['label']}') matches {score:.0%}. Affects {len(g['cases'])} case(s). "
                      f"Expected results are unchanged.")
            if g["workflow"]:
                reason += " Workflow steps live in project.yaml: rename the field there too."
        live.emit("healer", "heal", reason, path=path, old=missing, new=(new or {}).get("field"),
                  level="ok" if kind == "locator" else "warn")
        store.insert("heals", {"case_id": ",".join(g["cases"]), "run_id": run_id, "kind": kind,
                               "old": {"field": missing, "label": old.get("label"), "path": path},
                               "new": new, "reason": reason, "status": "proposed", "created_at": now()})
        proposed += kind == "locator"
    needs_review = manual + len(groups) - proposed
    proposed += store.scalar("SELECT COUNT(*) FROM heals WHERE status='proposed' AND kind='workflow' AND run_id=?", [run_id]) or 0
    return {"proposed": proposed, "needs_review": needs_review}


def approve_heal(store: Store, heal_id: int, approve: bool = True, project: Project | None = None, *,
                 by: str = "dashboard", why: str = "") -> str:
    """Apply an approved heal to the stored cases (and to project.yaml for workflows). Returns a note. The change log's
    reason is the person's `why` when they gave one, otherwise the Healer's own reason."""
    from agentqa import yamledit
    h = store.one("SELECT * FROM heals WHERE id=?", [heal_id])
    if not h:
        raise KeyError(heal_id)
    store.update("heals", "id", heal_id, {"status": "approved" if approve else "rejected"})
    from agentqa.store import now as _now
    store.insert("change_log", {"at": _now(), "agent": "healer", "object": "case", "object_id": h["case_id"] or "-",
                                "change": f"{'approved' if approve else 'rejected'} {h['kind']} fix: {json.dumps(h['old'])[:150]} "
                                          f"-> {json.dumps(h['new'])[:150]}",
                                "justification": why or h["reason"] or "", "by": by})
    if approve and h["kind"] == "workflow":
        wf, step, key = h["old"]["workflow"], int(h["old"]["step"]), h["old"]["key"]
        old_v, new_v = h["old"]["value"], h["new"]["value"]
        for c in store.all("SELECT * FROM cases WHERE type='workflow'"):
            params = c["params"] or {}
            if params.get("workflow_id") == wf and len(params.get("steps", [])) >= step \
                    and params["steps"][step - 1].get(key) == old_v:
                params["steps"][step - 1][key] = new_v
                store.update("cases", "id", c["id"], {"params": params})
        if project is not None:
            ok = yamledit.replace_in_workflow(project.config_path, wf, old_v, new_v, step=step, key=key)
            return ("project.yaml updated" if ok else
                    f"Could not find '{old_v}' in workflow {wf} in project.yaml: change it by hand")
        return "stored cases updated"
    if not (approve and h["kind"] == "locator"):
        return ""
    old_name, new_name, path = h["old"]["field"], h["new"]["field"], h["old"].get("path")
    # apply to every case on that screen that uses the old field name
    for c in store.all("SELECT * FROM cases WHERE path=?", [path]):
        params = c["params"] or {}
        changed = False
        if params.get("field") == old_name:
            params["field_override"] = new_name
            changed = True
        for key in ("base", "values"):
            if isinstance(params.get(key), dict) and old_name in params[key]:
                params[key][new_name] = params[key].pop(old_name)
                changed = True
        if changed:
            store.update("cases", "id", c["id"], {"params": params})
    renamed = failed = False
    for c in store.all("SELECT * FROM cases WHERE type='workflow'"):
        params = c["params"] or {}
        hit = False
        for st in params.get("steps", []):
            if old_name in (st.get("fill") or {}):
                st["fill"][new_name] = st["fill"].pop(old_name)
                hit = True
        if hit:
            store.update("cases", "id", c["id"], {"params": params})
            if project is not None:
                done = yamledit.rename_fill_key(project.config_path, params.get("workflow_id"), old_name, new_name)
                renamed, failed = renamed or done, failed or not done
    if failed:
        return f"Could not rename '{old_name[:80]}' in project.yaml: change it there by hand"
    return "project.yaml updated" if renamed else ""
