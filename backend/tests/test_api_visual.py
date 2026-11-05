"""M1.4 Phase C — visual review: a changed screen is approved as its new baseline (with a reason) or reported as a
draft defect. The two actions are the old dashboard's code moved, so the old route and the new one must leave the same
rows and files; what is new is that a stored path outside the project is never copied, and the change log."""
from __future__ import annotations

import shutil

from agentqa.store import Store
from conftest import CSRF, GATES_WHO

KEY = "citizen@citizen_apply"
RUN = "runs/run-20261105-100000/visual"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _files(root, key=KEY) -> dict[str, str]:
    """A run's three pictures of a changed screen, and the old baseline."""
    paths = {"current": f"{RUN}/{key}-current.png", "layout": f"{RUN}/{key}-layout.png", "diff": f"{RUN}/{key}-diff.png",
             "baseline": f"visual/baselines/{key}.png"}
    for name, rel in paths.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(PNG + name.encode())
    return {k: str(root / v) for k, v in paths.items()}


def _changed(g, key=KEY, **override) -> dict:
    files = _files(g.project.root, key)
    row = {"key": key, "role": "citizen", "path": "/apply", "status": "changed", "diff_ratio": 0.125,
           "baseline": files["baseline"], "current": files["current"], "diff": files["diff"],
           "run_id": "run-20261105-100000", "case_id": "TC-0190", "updated_at": "2026-11-05T10:00:00", **override}
    with g.db() as s:
        s.insert("visual", row, replace=True)
    return row


def _decide(g, key, decision, why=""):
    return g.client.post(f"{g.base}/visual/{key}", json={"decision": decision, "why": why}, headers=CSRF)


def _log(g) -> list[dict]:
    with g.db() as s:
        return s.all("SELECT object, object_id, change, justification, by FROM change_log WHERE object='visual'")


def test_changed_screens_come_with_counts_and_never_a_path(gates):
    _changed(gates)
    r = gates.client.get(f"{gates.base}/visual")
    data = r.json()["data"]
    assert [v["key"] for v in data["items"]] == [KEY]
    assert data["items"][0]["images"] == {"baseline": True, "current": True, "diff": True}
    assert set(data["items"][0]) == {"key", "role", "path", "status", "diff_ratio", "run_id", "case_id", "updated_at",
                                     "images"}
    assert data["counts"] == {"baseline": 20, "changed": 1} and data["total"] == 1
    assert str(gates.project.root) not in r.text and ".png" not in r.text and "runs/" not in r.text
    every = gates.client.get(f"{gates.base}/visual", params={"show": "all"}).json()["data"]
    assert every["total"] == 21 and every["items"][0]["key"] == KEY            # the changed one first
    assert gates.client.get(f"{gates.base}/visual", params={"show": "odd"}).status_code == 422


def test_pictures_go_through_the_guard_by_key_and_which(gates):
    _changed(gates)
    r = gates.client.get(f"{gates.base}/visual/{KEY}/current")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content.endswith(b"current")
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"
    assert gates.client.get(f"{gates.base}/visual/{KEY}/diff").content.endswith(b"diff")
    assert gates.client.get(f"{gates.base}/visual/{KEY}/layout").status_code == 422
    assert gates.client.get(f"{gates.base}/visual/nobody@nowhere/current").status_code == 404
    assert gates.client.get(f"{gates.base}/visual/a%20b/current").status_code == 422
    outside = gates.project.root.parent / "outside.png"
    outside.write_bytes(PNG)
    _changed(gates, current=str(outside))
    assert gates.client.get(f"{gates.base}/visual/{KEY}/current").status_code == 404


def test_approving_needs_a_reason_copies_the_pictures_and_is_logged(gates):
    _changed(gates)
    assert _decide(gates, KEY, "approve").status_code == 422
    r = _decide(gates, KEY, "approve", "the new header is intended")
    assert r.status_code == 200 and r.json()["data"] == {"key": KEY, "status": "approved"}
    base = gates.project.root / "visual" / "baselines"
    assert (base / f"{KEY}.png").read_bytes().endswith(b"current")
    assert (base / f"{KEY}-layout.png").read_bytes().endswith(b"layout")
    with gates.db() as s:
        row = s.one("SELECT status, baseline FROM visual WHERE key=?", [KEY])
    assert row == {"status": "approved", "baseline": str(base / f"{KEY}.png")}
    assert _log(gates) == [{"object": "visual", "object_id": KEY, "change": "approved as the new baseline",
                            "justification": "the new header is intended", "by": GATES_WHO}]


def test_reporting_makes_a_draft_defect_and_logs_its_id(gates):
    _changed(gates)
    r = _decide(gates, KEY, "defect")
    assert r.status_code == 200 and r.json()["data"] == {"key": KEY, "status": "reported", "defect": "DEF-020"}
    with gates.db() as s:
        d = s.one("SELECT * FROM defects WHERE id='DEF-020'")
    assert d["status"] == "draft" and d["signature"] == f"visual:{KEY}" and len(d["evidence"]) == 2
    assert _log(gates)[0]["change"] == "reported as DEF-020"


def test_a_path_outside_the_project_is_refused_and_nothing_is_copied(gates):
    outside = gates.project.root.parent / "outside-current.png"
    outside.write_bytes(PNG)
    for planted in (str(outside), "runs/../../outside-current.png"):
        _changed(gates, current=planted)
        r = _decide(gates, KEY, "approve", "looks fine")
        assert r.status_code == 409 and r.json()["error"]["code"] == "no_image"
        assert (gates.project.root / "visual" / "baselines" / f"{KEY}.png").read_bytes().endswith(b"baseline")
        with gates.db() as s:
            assert s.one("SELECT status FROM visual WHERE key=?", [KEY])["status"] == "changed"
    assert _log(gates) == []


def test_only_a_changed_screen_is_decided_and_never_while_a_run_goes(gates):
    assert _decide(gates, "admin@department", "approve", "x").status_code == 409             # a baseline
    assert _decide(gates, "nobody@nowhere", "defect").status_code == 404
    _changed(gates)
    gates.busy()
    assert _decide(gates, KEY, "defect").status_code == 409
    assert _decide(gates, KEY, "launch").status_code == 422


def test_approve_all_needs_a_reason_and_writes_one_row(gates):
    _changed(gates)
    _changed(gates, "officer@department", path="@department/")
    url = f"{gates.base}/visual/approve-all"
    assert gates.client.post(url, json={}, headers=CSRF).status_code == 422
    assert gates.client.post(url, json={"keys": ["nobody@nowhere"], "why": "x"}, headers=CSRF).status_code == 422
    assert gates.client.post(url, json={"keys": ["k"] * 201, "why": "x"}, headers=CSRF).status_code == 422
    r = gates.client.post(url, json={"keys": [KEY], "why": "the redesign shipped"}, headers=CSRF)
    assert r.json()["data"] == {"approved": 1, "skipped": 0}
    r = gates.client.post(url, json={"why": "the redesign shipped"}, headers=CSRF)
    assert r.json()["data"] == {"approved": 1, "skipped": 0}
    assert [x["change"] for x in _log(gates)] == ["approved 1 changed screen(s) as the new baselines"] * 2


def _snapshot(root) -> dict:
    with _open(root) as s:
        visual = s.all("SELECT key, role, path, status, diff_ratio, run_id, case_id FROM visual ORDER BY key")
        defects = s.all("SELECT id, signature, title, severity, status, steps, evidence, notes FROM defects "
                        "WHERE signature LIKE 'visual:%' ORDER BY id")
    baselines = {f.name: f.read_bytes() for f in sorted((root / "visual" / "baselines").glob("*.png"))}
    return {"visual": visual, "defects": _relative(defects, root), "baselines": baselines}


def _open(root):
    from contextlib import closing

    from agentqa.config import Project
    return closing(Store(Project(root).db_path))


def _relative(rows: list[dict], root) -> list[dict]:
    text = str(root)
    return [{**r, "evidence": [{**e, "path": e["path"].replace(text, "<root>")} for e in r["evidence"]]} for r in rows]


# ---- the v0.8 dashboard's two actions as they were at 118080d (web/app.py `_approve_visual` and `visual_action`),
# kept here word for word as the reference the moved code must match. The old routes now send a person to the app.

def _v08_approve(p, s, v: dict) -> None:
    from pathlib import Path as _Path

    from agentqa.store import now
    if not v.get("current"):
        return
    cur = _Path(v["current"])
    base = p.root / "visual" / "baselines"
    base.mkdir(parents=True, exist_ok=True)
    layout = cur.with_name(cur.name.replace("-current.png", "-layout.png"))
    shutil.copy(cur, base / f"{v['key']}.png")
    if layout.exists():
        shutil.copy(layout, base / f"{v['key']}-layout.png")
    s.update("visual", "key", v["key"], {"status": "approved", "baseline": str(base / f"{v['key']}.png"), "updated_at": now()})


def _v08_defect(p, s, key: str) -> None:
    from agentqa.store import now
    v = s.one("SELECT * FROM visual WHERE key=?", [key])
    sig = f"visual:{key}"
    old = s.one("SELECT * FROM defects WHERE signature=?", [sig])
    evidence = [{"kind": "difference", "role": v["role"], "path": v["diff"] or v["current"]},
                {"kind": "screenshot", "role": v["role"], "path": v["current"]}]
    row = {"run_id": v["run_id"], "case_ids": [v["case_id"]] if v["case_id"] else [], "signature": sig,
           "title": f"Unexpected visual change on {v['path']} ({v['role']})", "severity": "Medium", "priority": "P2",
           "role": v["role"], "url": p.url(v["path"]),
           "steps": f"Log in as {v['role']}.\nOpen {p.url(v['path'])}.\nCompare with the approved snapshot.",
           "expected": "The screen looks like its approved snapshot.",
           "actual": f"{(v['diff_ratio'] or 0):.2%} of the layout differs from the approved snapshot.",
           "evidence": evidence, "rule_ids": [], "req_ids": []}
    if old:
        s.update("defects", "id", old["id"], {**row, "status": "draft"})
    else:
        seq = (s.scalar("SELECT MAX(seq) FROM defects") or 0) + 1
        s.insert("defects", {"id": f"DEF-{seq:03d}", "seq": seq, **row, "status": "draft", "created_at": now(),
                             "notes": "Reported from Visual review.", "external_key": None})
    s.update("visual", "key", key, {"status": "reported", "updated_at": now()})


def test_the_moved_code_leaves_the_same_rows_and_files_as_the_v08_dashboard(gates):
    from agentqa.config import Project
    _changed(gates)
    _changed(gates, "officer@department", path="@department/", diff_ratio=0.3)
    twin = gates.project.root.parent / "demo2"
    shutil.copytree(gates.project.root, twin)
    with _open(twin) as s:                                     # the copy's stored paths point into the copy
        for v in s.all("SELECT key, baseline, current, diff FROM visual"):
            s.update("visual", "key", v["key"], {k: (v[k] or "").replace(str(gates.project.root), str(twin)) or None
                                                 for k in ("baseline", "current", "diff")})
        _v08_approve(Project(twin), s, s.one("SELECT * FROM visual WHERE key=?", [KEY]))
        _v08_defect(Project(twin), s, "officer@department")
    assert _decide(gates, KEY, "approve", "intended").status_code == 200
    assert _decide(gates, "officer@department", "defect").status_code == 200
    assert _snapshot(twin) == _snapshot(gates.project.root)


def test_a_copy_that_fails_part_way_still_logs_what_was_approved(gates, monkeypatch):
    import shutil as real_shutil

    from agentqa.orchestrator.gates import visual as visual_gate
    _changed(gates)
    _changed(gates, "officer@department", path="@department/")
    copied = []

    def flaky(src, dst):
        if len(copied) >= 2:                                  # the first screen's picture and layout, then a failure
            raise OSError("disk full")
        copied.append(dst)
        return real_shutil.copyfile(src, dst)
    monkeypatch.setattr(visual_gate.shutil, "copy", flaky)
    r = gates.client.post(f"{gates.base}/visual/approve-all", json={"why": "the redesign shipped"}, headers=CSRF)
    assert r.status_code == 503 and r.json()["error"]["code"] == "file_error"
    assert [x["change"] for x in _log(gates)] == ["approved 1 changed screen(s) as the new baselines"]


def test_no_decision_while_a_run_goes_from_the_app_or_the_command_line(gates, monkeypatch):
    _changed(gates)
    url = f"{gates.base}/visual/approve-all"
    with monkeypatch.context() as m:
        m.setattr("agentqa.orchestrator.live.cli_run_going", lambda p: True)
        assert gates.client.post(url, json={"why": "x"}, headers=CSRF).status_code == 409
        assert _decide(gates, KEY, "defect").status_code == 409
    gates.busy()
    assert gates.client.post(url, json={"why": "x"}, headers=CSRF).status_code == 409
