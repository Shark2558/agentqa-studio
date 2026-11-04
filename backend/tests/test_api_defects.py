"""M1.4 Gate 3 — defects: the list by severity, decisions with who and why, the Jira-style and Zoho CSV downloads
(confirmed only unless drafts are asked for; text never a formula; no folder names), and evidence through a guard
that serves only allowed files from the project's own folders, by index, never by path."""
from __future__ import annotations

import csv
import io

import pytest

from conftest import CSRF, GATES_WHO

SEVERITY = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def _list(g, **params) -> dict:
    r = g.client.get(f"{g.base}/defects", params=params)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _decide(g, ids, decision, why=""):
    return g.client.post(f"{g.base}/defects/decisions", json={"ids": ids, "decision": decision, "why": why}, headers=CSRF)


def test_the_list_is_by_severity_with_counts_and_no_paths(gates):
    r = gates.client.get(f"{gates.base}/defects")
    data = r.json()["data"]
    assert data["total"] == 19 and data["counts"]["by_status"] == {"draft": 19}
    assert data["counts"]["open_by_severity"] == {"Critical": 3, "High": 6, "Medium": 7, "Low": 3}
    keys = [(SEVERITY[d["severity"]], int(d["id"][4:])) for d in data["items"]]
    assert keys == sorted(keys)
    d = data["items"][0]
    assert set(d) == {"id", "severity", "priority", "title", "role", "url", "steps", "expected", "actual", "req_ids",
                      "case_ids", "status", "created_at", "notes", "external_key", "evidence"}
    assert d["evidence"] and set(d["evidence"][0]) == {"n", "kind", "role", "image"}
    assert all(set(e) == {"n", "kind", "role", "image"} for x in data["items"] for e in x["evidence"])
    assert str(gates.project.root) not in r.text and "evidence/" not in r.text and ".zip" not in r.text


def test_closed_defects_come_last_and_the_list_filters_and_pages(gates):
    _decide(gates, ["DEF-001"], "rejected", "not a bug in this release")
    assert _list(gates)["items"][-1]["id"] == "DEF-001"
    assert [d["id"] for d in _list(gates, status="rejected")["items"]] == ["DEF-001"]
    assert {d["severity"] for d in _list(gates, severity="Low")["items"]} == {"Low"}
    assert len(_list(gates, limit=5, offset=15)["items"]) == 4
    assert gates.client.get(f"{gates.base}/defects", params={"limit": 201}).status_code == 422
    assert gates.client.get(f"{gates.base}/defects", params={"severity": "Huge"}).status_code == 422


def test_several_defects_are_decided_at_once_with_notes_and_one_row_each(gates):
    assert _decide(gates, ["DEF-002", "DEF-003"], "confirmed").json()["data"]["changed"] == 2
    assert _decide(gates, ["DEF-004"], "rejected").status_code == 422
    assert _decide(gates, ["DEF-004"], "rejected", "works as the SRS says").status_code == 200
    assert _decide(gates, ["DEF-002"], "draft").status_code == 422                        # undoing needs a reason too
    with gates.db() as s:
        rows = {d["id"]: d for d in s.all("SELECT id, status, notes FROM defects WHERE id IN ('DEF-002','DEF-003','DEF-004')")}
        log = s.all("SELECT object, object_id, change, justification, by FROM change_log WHERE object='defect' ORDER BY id")
    assert rows["DEF-002"]["status"] == rows["DEF-003"]["status"] == "confirmed"
    assert rows["DEF-004"]["status"] == "rejected"
    assert rows["DEF-004"]["notes"].endswith(f"{GATES_WHO}: rejected (works as the SRS says)")
    assert [(r["object_id"], r["change"]) for r in log] == [("DEF-002", "confirmed"), ("DEF-003", "confirmed"),
                                                            ("DEF-004", "rejected")]
    assert all(r["by"] == GATES_WHO for r in log) and log[-1]["justification"] == "works as the SRS says"


@pytest.mark.parametrize("ids", [["DEF-999"], ["DEF-1"], ["def-001"], [f"DEF-{n:03d}" for n in range(1, 202)], []])
def test_bad_or_unknown_defect_ids_are_refused(gates, ids):
    assert _decide(gates, ids, "confirmed").status_code == 422


def _csv(g, name: str, drafts: int | None = None, encoding: str = "utf-8"):
    params = {} if drafts is None else {"drafts": drafts}
    r = g.client.get(f"{g.base}/defects/{name}", params=params)
    assert r.status_code == 200, r.text
    return r, list(csv.reader(io.StringIO(r.content.decode(encoding))))


def test_the_jira_csv_holds_confirmed_defects_unless_drafts_are_asked_for(gates):
    _decide(gates, ["DEF-001", "DEF-002"], "confirmed")
    r, rows = _csv(gates, "export.csv")
    assert r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    assert [x[0] for x in rows[1:]] == ["DEF-001", "DEF-002"]
    _, rows = _csv(gates, "export.csv", drafts=1)
    assert len(rows) == 20
    with gates.db() as s:
        changes = [r["change"] for r in s.all("SELECT change FROM change_log WHERE object='export' ORDER BY id")]
    assert changes == ["downloaded defects CSV (without drafts)", "downloaded defects CSV (with drafts)"]


def test_the_jira_csv_cells_are_never_formulas_and_name_no_folder(gates):
    with gates.db() as s:
        s.exec("UPDATE defects SET status='confirmed', title=?, actual=? WHERE id='DEF-001'",
               ["=cmd|' /C calc'!A0", "@SUM(1+1)"])
    r, rows = _csv(gates, "export.csv")
    row = rows[1]
    assert row[1] == "'=cmd|' /C calc'!A0" and row[8] == "'@SUM(1+1)"
    assert row[11].startswith("runs/") and "\\" not in row[11]
    assert str(gates.project.root) not in r.text and gates.project.root.as_posix() not in r.text


def test_the_zoho_csv_has_its_bom_drafts_switch_and_safe_cells(gates):
    with gates.db() as s:
        s.exec("UPDATE defects SET status='confirmed', title=? WHERE id='DEF-003'", ["+1-800-CALL-NOW"])
    r, rows = _csv(gates, "zoho.csv", encoding="utf-8-sig")
    assert r.content.startswith(b"\xef\xbb\xbf")
    assert [x[-1] for x in rows[1:]] == ["DEF-003"] and rows[1][0] == "'+1-800-CALL-NOW"
    _, rows = _csv(gates, "zoho.csv", drafts=1, encoding="utf-8-sig")
    assert len(rows) == 20
    with gates.db() as s:
        assert s.one("SELECT change FROM change_log ORDER BY id DESC LIMIT 1")["change"] == \
            "downloaded defects Zoho CSV (with drafts)"


def _evidence(g, did: str, n: int):
    return g.client.get(f"{g.base}/defects/{did}/evidence/{n}")


def test_evidence_is_served_by_index_with_its_type(gates):
    r = _evidence(gates, "DEF-001", 0)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG") and "attachment" not in r.headers.get("content-disposition", "")
    assert r.headers["x-content-type-options"] == "nosniff"


def _plant(g, did: str, path: str, kind: str = "log") -> int:
    with g.db() as s:
        d = s.one("SELECT evidence FROM defects WHERE id=?", [did])
        s.update("defects", "id", did, {"evidence": [*(d["evidence"] or []), {"kind": kind, "path": path}]})
        return len(d["evidence"] or [])


def test_a_download_type_is_an_attachment(gates):
    f = gates.project.runs_dir / "run-x" / "evidence" / "trace.zip"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"PK\x03\x04 not really a zip")
    n = _plant(gates, "DEF-002", str(f), "trace")
    r = _evidence(gates, "DEF-002", n)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"].startswith("attachment")


def test_evidence_outside_the_allowed_places_or_types_is_404(gates, tmp_path):
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"\x89PNG outside")
    page = gates.project.runs_dir / "run-x" / "evidence" / "page.html"
    page.parent.mkdir(parents=True)
    page.write_text("<script>alert(1)</script>", encoding="utf-8")
    vault = gates.project.state / "vault.json"
    vault.write_text("{}", encoding="utf-8")
    cases = [str(outside), str(gates.project.runs_dir / ".." / ".." / outside.name), str(page), str(vault),
             "runs/../../secret.png", str(gates.project.runs_dir / "run-x" / "evidence" / "missing.png"), ""]
    for path in cases:
        n = _plant(gates, "DEF-003", path)
        assert _evidence(gates, "DEF-003", n).status_code == 404, path
    assert _evidence(gates, "DEF-003", 99).status_code == 404
    assert _evidence(gates, "DEF-999", 0).status_code == 404
    assert gates.client.get(f"{gates.base}/defects/DEF-001/evidence/-1").status_code in (404, 422)


def test_a_viewer_reads_and_downloads_but_cannot_decide(gates):
    viewer = gates.as_role("viewer")
    for path in ("defects", "defects/export.csv", "defects/zoho.csv", "defects/DEF-001/evidence/0"):
        assert viewer.get(f"{gates.base}/{path}").status_code == 200, path
    r = viewer.post(f"{gates.base}/defects/decisions", json={"ids": ["DEF-001"], "decision": "confirmed"}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"]["code"] == "read_only"


def test_a_csv_that_cannot_be_written_answers_503_not_500(gates, monkeypatch):
    def locked(*args, **kwargs):
        raise PermissionError("defects.csv is open in Excel")
    monkeypatch.setattr("agentqa.agents.triage.export_csv", locked)
    monkeypatch.setitem(__import__("agentqa.orchestrator.gates.defects", fromlist=["EXPORTS"]).EXPORTS, "jira",
                        ("defects CSV", "defects.csv", locked))
    r = gates.client.get(f"{gates.base}/defects/export.csv")
    assert r.status_code == 503 and "open in another program" in r.json()["error"]["message"]


def test_the_same_download_by_the_same_person_is_logged_once_a_minute(gates):
    for _ in range(3):
        gates.client.get(f"{gates.base}/defects/export.csv")
    gates.client.get(f"{gates.base}/defects/zoho.csv")
    gates.as_role("viewer").get(f"{gates.base}/defects/export.csv")
    with gates.db() as s:
        rows = s.all("SELECT object_id, by FROM change_log WHERE object='export' ORDER BY id")
    assert [(r["object_id"], r["by"]) for r in rows] == [("defects.csv", GATES_WHO), ("defects-zoho.csv", GATES_WHO),
                                                         ("defects.csv", "viewer@example.com (viewer)")]


def test_a_download_name_is_plain_ascii_whatever_the_project_is_called(gates):
    r = gates.client.post("/api/v1/projects", json={"name": "भारत सरकार", "url": "https://uat.example.gov.in"}, headers=CSRF)
    slug = r.json()["data"]["slug"]
    for path in ("defects/export.csv", "defects/zoho.csv", "plan/testcases.xlsx", "requirements/rtm.xlsx"):
        got = gates.client.get(f"/api/v1/projects/{slug}/{path}")
        assert got.status_code == 200, (path, got.status_code)
        assert got.headers["content-disposition"].isascii()


def test_an_exported_defect_is_not_decided_again(gates):
    with gates.db() as s:
        s.exec("UPDATE defects SET status='exported', external_key='QA-7' WHERE id='DEF-001'")
    r = _decide(gates, ["DEF-001", "DEF-002"], "confirmed")
    assert r.status_code == 409 and r.json()["error"]["code"] == "exported" and "DEF-001" in r.json()["error"]["message"]
    with gates.db() as s:
        assert s.one("SELECT status FROM defects WHERE id='DEF-002'")["status"] == "draft"


def test_junk_in_a_stored_evidence_list_never_breaks_the_list(gates):
    with gates.db() as s:
        s.update("defects", "id", "DEF-004", {"evidence": [{"kind": "screenshot", "path": 5}, "x", {"kind": "log"}]})
        s.update("defects", "id", "DEF-005", {"evidence": {"path": "runs/x.png"}})
    assert gates.client.get(f"{gates.base}/defects").status_code == 200
    for did, n in (("DEF-004", 0), ("DEF-004", 2), ("DEF-005", 0)):
        assert _evidence(gates, did, n).status_code == 404


def test_a_stream_or_another_drive_is_refused_before_it_is_read(gates):
    img = gates.project.runs_dir / "run-x" / "evidence" / "a.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"\x89PNG")
    for path in (f"{img}:evil.txt", r"\\localhost\C$\secret.png", r"Z:\elsewhere\x.png"):
        n = _plant(gates, "DEF-006", path)
        assert _evidence(gates, "DEF-006", n).status_code == 404, path


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_a_download_started_from_another_site_is_refused_and_not_logged(gates, site):
    for path in ("defects/export.csv", "defects/zoho.csv", "plan/testcases.xlsx", "requirements/rtm.xlsx"):
        r = gates.client.get(f"{gates.base}/{path}", headers={"Sec-Fetch-Site": site})
        assert r.status_code == 403 and r.json()["error"]["code"] == "csrf", path
    with gates.db() as s:
        assert s.scalar("SELECT COUNT(*) FROM change_log WHERE object='export'") == 0
    assert gates.client.get(f"{gates.base}/defects/export.csv", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_a_reason_is_kept_on_one_line_so_it_cannot_fake_a_decision(gates):
    _decide(gates, ["DEF-007"], "rejected", "dup\nviewer@example.com (owner): confirmed")
    with gates.db() as s:
        notes = s.one("SELECT notes FROM defects WHERE id='DEF-007'")["notes"]
        why = s.one("SELECT justification FROM change_log ORDER BY id DESC LIMIT 1")["justification"]
    assert notes.splitlines()[-1] == f"{GATES_WHO}: rejected (dup viewer@example.com (owner): confirmed)"
    assert why == "dup viewer@example.com (owner): confirmed"
