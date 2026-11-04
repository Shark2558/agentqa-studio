"""M1.4 pinning tests: what the three gates' engine functions do *today*, written before anything moves, so the new
services can only add to it (plan m1-4-gates.md, "Tests first", facts 4–6 and 8)."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
import yaml

from agentqa.agents import designer, healer, reconciler, requirements, triage
from gates_rows import case, defect, heal, question, requirement


# ---- Gate 1: questions --------------------------------------------------------------------------

def test_an_answer_stores_the_options_label_the_value_and_one_log_row(demo):
    _, s = demo
    qid = question(s, 1, req_id="FR-03")
    reconciler.answer_question(s, qid, 2, "10 digits")
    q = s.one("SELECT * FROM questions WHERE id=?", [qid])
    assert q["status"] == "answered" and q["answer"] == "Neither: I will enter the correct value"
    assert json.loads(q["answer_value"]) == {"choice": 2, "value": "10 digits"} and q["answered_at"]
    rows = s.all("SELECT * FROM change_log")
    assert len(rows) == 1
    row = rows[0]
    assert (row["agent"], row["object"], row["object_id"], row["by"]) == ("person", "question", str(qid), "dashboard")
    assert row["change"] == "answered 'Neither: I will enter the correct value' (10 digits) for FR-03"
    assert row["justification"] == "Question 1?"


def test_an_answer_out_of_range_keeps_the_number_and_an_answered_question_can_be_answered_again(demo):
    _, s = demo
    qid = question(s, 1, req_id=None)
    reconciler.answer_question(s, qid, 7)
    assert s.one("SELECT answer FROM questions WHERE id=?", [qid])["answer"] == 7     # "7" read back as JSON
    reconciler.answer_question(s, qid, 0)                                             # no "still open" check today
    assert s.one("SELECT answer FROM questions WHERE id=?", [qid])["answer"].startswith("SRS is correct")
    assert s.one("SELECT change FROM change_log ORDER BY id DESC LIMIT 1")["change"].endswith("for R-001")


def test_answering_an_unknown_question_raises_key_error(demo):
    with pytest.raises(KeyError):
        reconciler.answer_question(demo[1], 99, 0)


# ---- Gate 2: the test plan ----------------------------------------------------------------------

def _statuses(s) -> dict[str, str]:
    return {c["id"]: c["status"] for c in s.all("SELECT id, status FROM cases ORDER BY seq")}


def test_approving_by_ids_changes_those_cases_whatever_their_status_and_not_the_plan(demo):
    p, s = demo
    for n in (1, 2, 3):
        case(s, n)
    case(s, 4, status="rejected")
    designer.plan(p, s)
    assert designer.approve(s, case_ids=["TC-0001", "TC-0004"]) == 2
    assert _statuses(s) == {"TC-0001": "approved", "TC-0002": "proposed", "TC-0003": "proposed", "TC-0004": "approved"}
    assert designer.approve(s, case_ids=["TC-0002"], reject=True) == 1
    assert _statuses(s)["TC-0002"] == "rejected"
    assert s.one("SELECT approved FROM plan WHERE id=1")["approved"] == 0


def test_approving_by_type_changes_only_that_types_proposed_cases_and_not_the_plan(demo):
    p, s = demo
    case(s, 1, type="access_denied")
    case(s, 2, type="access_denied", status="rejected")
    case(s, 3)
    designer.plan(p, s)
    assert designer.approve(s, case_types=["access_denied"]) == 1
    assert _statuses(s) == {"TC-0001": "approved", "TC-0002": "rejected", "TC-0003": "proposed"}
    assert s.one("SELECT approved FROM plan WHERE id=1")["approved"] == 0


def test_only_approving_everything_approves_the_plan(demo):
    p, s = demo
    case(s, 1)
    case(s, 2, status="rejected")
    designer.plan(p, s)
    assert designer.approve(s) == 1
    plan = s.one("SELECT * FROM plan WHERE id=1")
    assert plan["approved"] == 1 and plan["approved_at"]
    assert _statuses(s) == {"TC-0001": "approved", "TC-0002": "rejected"}


def test_rejecting_everything_also_marks_the_plan_approved(demo):
    """A trap the new service must avoid: `approve(s, reject=True)` without ids or types rejects every proposed case
    *and* sets the plan approved."""
    p, s = demo
    case(s, 1)
    designer.plan(p, s)
    assert designer.approve(s, reject=True) == 1
    assert _statuses(s) == {"TC-0001": "rejected"}
    assert s.one("SELECT approved FROM plan WHERE id=1")["approved"] == 1


def test_a_plan_keeps_its_approval_while_the_case_set_stays_and_loses_it_when_it_changes(demo):
    p, s = demo
    case(s, 1)
    first = designer.plan(p, s)
    designer.approve(s)
    assert designer.plan(p, s)["digest"] == first["digest"]
    assert s.one("SELECT approved FROM plan WHERE id=1")["approved"] == 1
    case(s, 2)
    assert designer.plan(p, s)["digest"] != first["digest"]
    plan = s.one("SELECT * FROM plan WHERE id=1")
    assert plan["approved"] == 0 and plan["approved_at"] is None and plan["summary"]["cases"] == 2


# ---- Gate 3: defects ----------------------------------------------------------------------------

def test_a_defect_decision_sets_the_status_and_appends_the_note(demo):
    _, s = demo
    defect(s, 1, notes="Found in R-1.")
    defect(s, 2)
    triage.set_defect_status(s, ["DEF-001", "DEF-002"], "rejected", "not a bug")
    triage.set_defect_status(s, ["DEF-001"], "confirmed")
    rows = {d["id"]: d for d in s.all("SELECT * FROM defects")}
    assert rows["DEF-001"]["status"] == "confirmed" and rows["DEF-001"]["notes"] == "Found in R-1.\nnot a bug"
    assert rows["DEF-002"]["status"] == "rejected" and rows["DEF-002"]["notes"] == "\nnot a bug"
    assert s.scalar("SELECT COUNT(*) FROM change_log") == 0                           # nothing logged today


JIRA_HEADER = ["Defect ID", "Summary", "Severity", "Priority", "Role", "URL", "Steps to reproduce", "Expected result",
               "Actual result", "Requirement IDs", "Test cases", "Evidence", "Status"]
ZOHO_HEADER = ["Title", "Description", "Severity", "Classification", "Reproducible", "Module", "Status", "Flag",
               "Due Date", "AgentQA ID"]


def _three_defects(s) -> None:
    defect(s, 1, status="confirmed")
    defect(s, 2, status="draft")
    defect(s, 3, status="rejected")


def test_the_jira_csv_has_its_columns_no_bom_and_drafts_only_when_asked(demo):
    p, s = demo
    _three_defects(s)
    path = triage.export_csv(p, s)
    raw = Path(path).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(raw.decode("utf-8").splitlines()))
    assert rows[0] == JIRA_HEADER and [r[0] for r in rows[1:]] == ["DEF-001"]
    assert rows[1][9] == "FR-01" and rows[1][10] == "TC-0001" and rows[1][12] == "confirmed"
    rows = _read(triage.export_csv(p, s, include_drafts=True), "utf-8")
    assert [r[0] for r in rows[1:]] == ["DEF-001", "DEF-002"]


def _read(path: str, encoding: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(Path(path).read_text(encoding=encoding), newline="")))


def test_the_zoho_csv_has_its_columns_a_bom_and_includes_drafts_by_default(demo):
    p, s = demo
    _three_defects(s)
    path = triage.export_zoho_csv(p, s)
    assert Path(path).read_bytes().startswith(b"\xef\xbb\xbf")
    rows = _read(path, "utf-8-sig")
    assert rows[0] == ZOHO_HEADER and [r[-1] for r in rows[1:]] == ["DEF-001", "DEF-002"]
    assert rows[1][2] == "Critical" and rows[1][5] == "/apply"                       # High -> Zoho "Critical"
    rows = _read(triage.export_zoho_csv(p, s, include_drafts=False), "utf-8-sig")
    assert [r[-1] for r in rows[1:]] == ["DEF-001"]


# ---- Heals --------------------------------------------------------------------------------------

def test_an_approved_locator_heal_renames_the_field_in_that_screens_cases_and_is_logged(demo):
    p, s = demo
    case(s, 1, params={"field": "mobile"})
    case(s, 2, params={"values": {"mobile": "98765", "name": "A"}})
    case(s, 3, path="/other", params={"field": "mobile"})
    hid = heal(s)
    assert healer.approve_heal(s, hid, project=p) == ""
    params = {c["id"]: c["params"] for c in s.all("SELECT id, params FROM cases")}
    assert params["TC-0001"] == {"field": "mobile", "field_override": "mobile_no"}
    assert params["TC-0002"] == {"values": {"name": "A", "mobile_no": "98765"}}
    assert params["TC-0003"] == {"field": "mobile"}
    assert s.one("SELECT status FROM heals WHERE id=?", [hid])["status"] == "approved"
    row = s.one("SELECT * FROM change_log")
    assert (row["agent"], row["object"], row["object_id"], row["by"]) == ("healer", "case", "TC-0001", "dashboard")
    assert row["change"].startswith("approved locator fix: ") and row["justification"] == "the field was renamed"


def test_a_rejected_heal_changes_no_case(demo):
    p, s = demo
    case(s, 1, params={"field": "mobile"})
    hid = heal(s)
    assert healer.approve_heal(s, hid, approve=False, project=p) == ""
    assert s.one("SELECT params FROM cases")["params"] == {"field": "mobile"}
    assert s.one("SELECT status FROM heals")["status"] == "rejected"
    assert s.one("SELECT change FROM change_log")["change"].startswith("rejected locator fix")


WORKFLOW = """workflows:
  - id: WF-01
    steps:
      - role: clerk
        click: "text=Verify {app_id}"   # the clerk's button
"""


def test_an_approved_workflow_heal_updates_the_cases_and_project_yaml(demo):
    p, s = demo
    p.config_path.write_text(p.config_path.read_text(encoding="utf-8").replace("workflows: []\n", WORKFLOW),
                             encoding="utf-8")
    steps = [{"role": "clerk", "click": "text=Verify {app_id}"}]
    case(s, 1, type="workflow", params={"workflow_id": "WF-01", "steps": steps})
    hid = heal(s, kind="workflow", old={"workflow": "WF-01", "step": 1, "key": "click", "value": "text=Verify {app_id}"},
               new={"value": "text=Mark verified {app_id}"})
    assert healer.approve_heal(s, hid, project=p) == "project.yaml updated"
    assert s.one("SELECT params FROM cases")["params"]["steps"][0]["click"] == "text=Mark verified {app_id}"
    text = p.config_path.read_text(encoding="utf-8")
    assert "# the clerk's button" in text
    assert yaml.safe_load(text)["workflows"][0]["steps"][0]["click"] == "text=Mark verified {app_id}"


# ---- Requirements -------------------------------------------------------------------------------

def test_a_disposition_is_kept_as_an_override_and_logged(demo):
    _, s = demo
    requirement(s, 1)
    requirements.set_disposition(s, "FR-01", "manual", "checked by hand each release")
    r = s.one("SELECT disposition, disposition_note FROM requirements")
    assert (r["disposition"], r["disposition_note"]) == ("manual", "checked by hand each release")
    assert s.get_meta("req_dispositions") == {"FR-01": {"disposition": "manual", "note": "checked by hand each release"}}
    row = s.one("SELECT * FROM change_log")
    assert (row["agent"], row["object"], row["object_id"], row["by"]) == ("person", "requirement", "FR-01", "dashboard")
    assert row["change"] == "disposition set to Manual test only"


def test_an_unknown_disposition_is_refused(demo):
    with pytest.raises(ValueError):
        requirements.set_disposition(demo[1], "FR-01", "done")
