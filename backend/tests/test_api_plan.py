"""M1.4 Gate 2 — the test plan: summary, gaps, cases by type, imported manual cases; decisions per case, per type or all
at once (a reason to reject or undo); approval against the fingerprint the person reviewed; the Excel download."""
from __future__ import annotations

import io
import re

import pytest
from openpyxl import load_workbook

from conftest import CSRF, GATES_WHO


@pytest.fixture
def gate(gates):
    """The fixture as it stood at the plan gate: every case proposed, the plan not approved, imported cases ready."""
    with gates.db() as s:
        s.exec("UPDATE cases SET status='proposed'")
        s.exec("UPDATE plan SET approved=0, approved_at=NULL")
        s.exec("UPDATE manual_cases SET status='ready' WHERE status='approved'")
    return gates


def _plan(g) -> dict:
    r = g.client.get(f"{g.base}/plan")
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _post(g, path: str, body: dict):
    return g.client.post(f"{g.base}/plan{path}", json=body, headers=CSRF)


def _statuses(g, ids) -> list[str]:
    with g.db() as s:
        return [s.one("SELECT status FROM cases WHERE id=?", [i])["status"] for i in ids]


def _last_log(g) -> dict:
    with g.db() as s:
        return s.one("SELECT * FROM change_log ORDER BY id DESC LIMIT 1")


def test_the_overview_has_the_plan_its_types_gaps_and_imported_cases(gate):
    data = _plan(gate)
    assert data["plan"]["approved"] is False and data["plan"]["approved_at"] is None
    assert re.fullmatch(r"[0-9a-f]{12}", data["plan"]["digest"]) and data["plan"]["summary"]["cases"] == 206
    assert sum(t["cases"] for t in data["types"]) == 206 and all(t["proposed"] == t["cases"] for t in data["types"])
    assert {t["type"] for t in data["types"]} >= {"functional", "access_denied", "visual_snapshot"}
    assert set(data["gaps"]) == {"untested", "clarify", "unread", "missed", "workflow", "production"}
    assert len(data["gaps"]["clarify"]) == 5
    assert data["imported"] == {"ready": 9, "review": 1, "approved": 0, "rejected": 0}
    assert data["running"] is False
    gate.busy()
    assert _plan(gate)["running"] is True


def test_cases_page_by_type_and_status(gate):
    r = gate.client.get(f"{gate.base}/plan/cases", params={"type": "access_denied", "limit": 5})
    data = r.json()["data"]
    assert data["total"] == 22 and len(data["items"]) == 5
    assert set(data["items"][0]) == {"id", "type", "title", "role", "path", "priority", "oracle_source", "req_ids", "status"}
    assert gate.client.get(f"{gate.base}/plan/cases", params={"status": "approved"}).json()["data"]["total"] == 0
    assert gate.client.get(f"{gate.base}/plan/cases", params={"limit": 201}).status_code == 422
    assert gate.client.get(f"{gate.base}/plan/cases", params={"type": "x;DROP"}).status_code == 422


@pytest.mark.parametrize("ids", [["TC-9999"], ["TC-1"], ["../x"], [f"TC-{n:04d}" for n in range(1, 502)], []])
def test_bad_or_unknown_case_ids_are_refused(gate, ids):
    r = _post(gate, "/cases", {"ids": ids, "decision": "approve"})
    assert r.status_code == 422


def test_rejecting_cases_needs_a_reason_and_writes_one_row(gate):
    ids = ["TC-0001", "TC-0002", "TC-0003"]
    assert _post(gate, "/cases", {"ids": ids, "decision": "reject"}).status_code == 422
    assert _post(gate, "/cases", {"ids": ids, "decision": "reject", "why": "   "}).status_code == 422
    r = _post(gate, "/cases", {"ids": ids, "decision": "reject", "why": "duplicates of the login checks"})
    assert r.status_code == 200 and r.json()["data"]["changed"] == 3
    assert _statuses(gate, ids) == ["rejected"] * 3
    row = _last_log(gate)
    assert row["change"] == "rejected 3 case(s): TC-0001, TC-0002, TC-0003"
    assert row["justification"] == "duplicates of the login checks" and row["by"] == GATES_WHO
    assert r.json()["data"]["plan"]["approved"] is False


def test_approving_a_case_needs_no_reason_and_reset_needs_one(gate):
    assert _post(gate, "/cases", {"ids": ["TC-0004"], "decision": "approve"}).status_code == 200
    assert _statuses(gate, ["TC-0004"]) == ["approved"]
    assert _post(gate, "/cases", {"ids": ["TC-0004"], "decision": "reset"}).status_code == 422
    assert _post(gate, "/cases", {"ids": ["TC-0004"], "decision": "reset", "why": "look again"}).status_code == 200
    assert _statuses(gate, ["TC-0004"]) == ["proposed"]
    assert _last_log(gate)["change"] == "sent 1 case(s) back to proposed: TC-0004"


def test_a_long_list_of_ids_is_summarised_in_the_log(gate):
    ids = [f"TC-{n:04d}" for n in range(1, 41)]
    _post(gate, "/cases", {"ids": ids, "decision": "approve"})
    change = _last_log(gate)["change"]
    assert change.startswith("approved 40 case(s): TC-0001, ") and change.endswith("and 30 more")


def test_a_whole_type_is_decided_at_once(gate):
    assert _post(gate, "/types/access_denied", {"decision": "reject"}).status_code == 422
    r = _post(gate, "/types/access_denied", {"decision": "approve"})
    assert r.status_code == 200 and r.json()["data"]["changed"] == 22
    assert _last_log(gate)["change"] == "approved 22 access_denied case(s)"
    assert _post(gate, "/types/no_such_type", {"decision": "approve"}).status_code == 422
    assert _post(gate, "/types/Bad-Type", {"decision": "approve"}).status_code == 422


def test_imported_manual_cases_are_decided_explicitly(gate):
    r = _post(gate, "/imported", {"decision": "approve_ready"})
    assert r.status_code == 200 and r.json()["data"]["changed"] == 9
    assert _plan(gate)["imported"] == {"ready": 0, "review": 1, "approved": 9, "rejected": 0}
    with gate.db() as s:
        one = s.one("SELECT id FROM manual_cases WHERE status='approved' ORDER BY id")["id"]
    assert _post(gate, "/imported", {"ids": [one], "decision": "reject"}).status_code == 422
    assert _post(gate, "/imported", {"ids": [one], "decision": "review", "why": "steps unclear"}).status_code == 200
    assert _post(gate, "/imported", {"ids": ["NOPE-1"], "decision": "approve"}).status_code == 422
    assert _post(gate, "/imported", {"decision": "approve"}).status_code == 422             # approve needs ids
    assert _last_log(gate)["object"] == "imported case"


def test_the_plan_is_approved_against_the_fingerprint_the_person_reviewed(gate):
    digest = _plan(gate)["plan"]["digest"]
    _post(gate, "/cases", {"ids": ["TC-0001"], "decision": "reject", "why": "not needed"})
    stale = _post(gate, "/approve", {"digest": "0" * 12})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "plan_changed"
    r = _post(gate, "/approve", {"digest": digest, "why": "reviewed with the team"})
    assert r.status_code == 200 and r.json()["data"]["approved"] is True
    with gate.db() as s:
        assert s.scalar("SELECT COUNT(*) FROM cases WHERE status='proposed'") == 0
        assert s.one("SELECT approved FROM plan")["approved"] == 1
    row = _last_log(gate)
    assert row["change"] == "approved the plan: 205 approved, 1 rejected" and row["by"] == GATES_WHO
    assert row["object"] == "plan" and row["justification"] == "reviewed with the team"


def test_no_plan_decision_is_taken_while_a_job_runs(gate):
    digest = _plan(gate)["plan"]["digest"]
    gate.busy()
    for path, body in (("/approve", {"digest": digest}), ("/cases", {"ids": ["TC-0001"], "decision": "approve"}),
                       ("/types/functional", {"decision": "approve"}), ("/imported", {"decision": "approve_ready"})):
        r = _post(gate, path, body)
        assert r.status_code == 409 and r.json()["error"]["code"] == "busy", path
    with gate.db() as s:
        assert s.scalar("SELECT COUNT(*) FROM change_log WHERE by=?", [GATES_WHO]) == 0
        assert s.scalar("SELECT COUNT(*) FROM cases WHERE status='approved'") == 0


def test_approving_without_a_plan_is_refused(gate):
    with gate.db() as s:
        s.exec("DELETE FROM plan")
    r = _post(gate, "/approve", {"digest": "0" * 12})
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_plan"


def test_the_excel_file_is_safe_and_its_download_is_logged(gate):
    with gate.db() as s:
        s.exec("UPDATE cases SET title=? WHERE id='TC-0001'", ['=HYPERLINK("http://evil.example","Click")'])
    r = gate.client.get(f"{gate.base}/plan/testcases.xlsx")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert re.fullmatch(r'attachment; filename="[A-Za-z0-9-]+-test-cases\.xlsx"', r.headers["content-disposition"])
    ws = load_workbook(io.BytesIO(r.content))["Test cases"]
    cells = [c for row in ws.iter_rows() for c in row if isinstance(c.value, str) and "HYPERLINK" in c.value]
    assert cells and all(c.data_type == "s" and c.value.startswith("'=") for c in cells)
    assert _last_log(gate)["change"] == "downloaded the test cases (Excel)" and _last_log(gate)["by"] == GATES_WHO


def test_starting_a_run_that_approves_by_itself_is_logged(gates):
    r = gates.client.post(f"{gates.base}/runs", json={"scope": "pipeline", "auto_approve": True}, headers=CSRF)
    assert r.status_code == 202
    row = _last_log(gates)
    assert row["change"] == "started a run that approves the test plan by itself" and row["by"] == GATES_WHO
    gates.client.post(f"{gates.base}/runs", json={"scope": "pipeline"}, headers=CSRF)     # busy now; nothing logged
    assert _last_log(gates)["id"] == row["id"]


def test_a_viewer_reads_the_plan_and_downloads_it_but_cannot_decide(gate):
    viewer = gate.as_role("viewer")
    assert viewer.get(f"{gate.base}/plan").status_code == 200
    assert viewer.get(f"{gate.base}/plan/cases").status_code == 200
    assert viewer.get(f"{gate.base}/plan/testcases.xlsx").status_code == 200
    r = viewer.post(f"{gate.base}/plan/approve", json={"digest": "0" * 12}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"]["code"] == "read_only"


@pytest.mark.parametrize("mid", ["TC 001", "Login/01", "TC_001 (a)", "Ref: 7#2"])
def test_imported_case_ids_from_a_sheet_are_taken_as_written(gate, mid):
    """The id is the sheet's own "test case id" cell (importer.py): any text, looked up exactly."""
    with gate.db() as s:
        s.insert("manual_cases", {"id": mid, "title": "t", "role": "citizen", "steps": "s", "expected": "e",
                                  "converted": {}, "coverage": 1.0, "status": "ready", "source_file": "x.xlsx"})
    r = _post(gate, "/imported", {"ids": [mid], "decision": "approve"})
    assert r.status_code == 200 and r.json()["data"]["changed"] == 1


@pytest.mark.parametrize("mid", ["", "a\x00b", "line\nbreak", "x" * 201])
def test_imported_ids_with_control_characters_or_too_long_are_refused(gate, mid):
    assert _post(gate, "/imported", {"ids": [mid], "decision": "approve"}).status_code == 422


def test_a_decision_that_changes_nothing_writes_no_row(gate):
    _post(gate, "/types/access_denied", {"decision": "approve"})
    with gate.db() as s:
        before = s.scalar("SELECT COUNT(*) FROM change_log")
        s.exec("UPDATE manual_cases SET status='approved' WHERE status='ready'")
    assert _post(gate, "/types/access_denied", {"decision": "approve"}).json()["data"]["changed"] == 0
    assert _post(gate, "/imported", {"decision": "approve_ready"}).json()["data"]["changed"] == 0
    with gate.db() as s:
        assert s.scalar("SELECT COUNT(*) FROM change_log") == before


def test_every_case_type_the_designer_makes_can_be_filtered_and_decided(gate):
    from agentqa.api.schemas_gates import CASE_TYPE
    types = [t["type"] for t in _plan(gate)["types"]]
    assert "a11y_basic" in types and all(re.fullmatch(CASE_TYPE, t) for t in types)
    assert gate.client.get(f"{gate.base}/plan/cases", params={"type": "a11y_basic"}).json()["data"]["total"] == 15
    assert _post(gate, "/types/a11y_basic", {"decision": "approve"}).json()["data"]["changed"] == 15


def test_the_service_never_turns_an_empty_id_list_into_approve_all(gate):
    from agentqa.orchestrator.gates import GateError, plan
    with gate.db() as s:
        with pytest.raises(GateError) as err:
            plan.decide_cases(s, [], "approve", "", GATES_WHO)
        assert err.value.status == 422 and s.scalar("SELECT COUNT(*) FROM cases WHERE status='approved'") == 0
