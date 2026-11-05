"""M1.4 Phase C — heals: the Healer's proposed fixes, approved or rejected by a person (with a reason to reject).
Only a proposed locator or workflow fix can be decided. A workflow fix writes project.yaml with a value that comes from
the tested site, so a hostile value must still leave valid YAML with nothing else changed."""
from __future__ import annotations

import yaml

from conftest import CSRF, GATES_WHO

WORKFLOW = """workflows:
  - id: WF-01
    steps:
      - role: clerk
        click: "text=Verify {app_id}"   # the clerk's button
"""
LOCATOR = {"old": {"field": "mobile", "label": "Mobile", "path": "/apply"},
           "new": {"field": "mobile_no", "label": "Mobile number"}}


def _heal(g, kind="locator", status="proposed", old=None, new=None, case_id="TC-0190") -> int:
    with g.db() as s:
        return s.insert("heals", {"case_id": case_id, "run_id": "run-20261105-100000", "kind": kind,
                                  "old": old if old is not None else LOCATOR["old"],
                                  "new": new if new is not None else LOCATOR["new"],
                                  "reason": "the field was renamed", "status": status,
                                  "created_at": "2026-11-05T10:00:00"})


def _decide(g, hid, decision, why=""):
    return g.client.post(f"{g.base}/heals/{hid}", json={"decision": decision, "why": why}, headers=CSRF)


def _case_params(g, cid: str) -> dict:
    with g.db() as s:
        return s.one("SELECT params FROM cases WHERE id=?", [cid])["params"]


def test_proposed_fixes_come_first_and_say_whether_they_can_be_decided(gates):
    done = _heal(gates, status="approved")
    manual = _heal(gates, kind="manual", old={"message": "x" * 900, "nested": {"a": 1}}, new={})
    locator = _heal(gates)
    data = gates.client.get(f"{gates.base}/heals").json()["data"]
    assert [h["id"] for h in data["items"]] == [locator, manual, done]
    assert [h["decidable"] for h in data["items"]] == [True, False, False]
    assert data["items"][0]["old"] == LOCATOR["old"] and data["items"][0]["new"] == LOCATOR["new"]
    assert data["items"][1]["old"] == {"message": "x" * 200}                  # capped, nested values left out
    assert data["counts"] == {"proposed": 2, "approved": 1} and data["total"] == 3
    assert gates.client.get(f"{gates.base}/heals", params={"status": "approved"}).json()["data"]["total"] == 1
    assert gates.client.get(f"{gates.base}/heals", params={"status": "maybe"}).status_code == 422


def test_approving_a_locator_fix_changes_the_cases_and_is_logged_with_who(gates):
    with gates.db() as s:
        s.exec("UPDATE cases SET path='/apply', params=? WHERE id='TC-0190'", ['{"field": "mobile"}'])
    hid = _heal(gates)
    r = _decide(gates, hid, "approve")
    assert r.status_code == 200 and r.json()["data"] == {"id": hid, "status": "approved", "note": ""}
    assert _case_params(gates, "TC-0190") == {"field": "mobile", "field_override": "mobile_no"}
    with gates.db() as s:
        row = s.one("SELECT agent, change, justification, by FROM change_log ORDER BY id DESC LIMIT 1")
    assert row["agent"] == "healer" and row["by"] == GATES_WHO and row["change"].startswith("approved locator fix")
    assert row["justification"] == "the field was renamed"                    # the Healer's reason when none is given


def test_a_reason_to_reject_is_required_and_kept(gates):
    hid = _heal(gates)
    assert _decide(gates, hid, "reject").status_code == 422
    assert _decide(gates, hid, "reject", "the old field comes back next release").status_code == 200
    with gates.db() as s:
        assert s.one("SELECT status FROM heals WHERE id=?", [hid])["status"] == "rejected"
        row = s.one("SELECT change, justification, by FROM change_log ORDER BY id DESC LIMIT 1")
    assert row == {"change": row["change"], "justification": "the old field comes back next release", "by": GATES_WHO}
    assert row["change"].startswith("rejected locator fix")


def _with_workflow(g) -> None:
    path = g.project.config_path
    path.write_text(path.read_text(encoding="utf-8").replace("workflows: []\n", WORKFLOW), encoding="utf-8")
    with g.db() as s:
        s.exec("UPDATE cases SET type='workflow', params=? WHERE id='TC-0190'",
               ['{"workflow_id": "WF-01", "steps": [{"role": "clerk", "click": "text=Verify {app_id}"}]}'])


def _workflow_heal(g, new_value: str) -> int:
    return _heal(g, kind="workflow", old={"workflow": "WF-01", "step": 1, "key": "click", "value": "text=Verify {app_id}"},
                 new={"value": new_value, "offered": new_value})


def test_a_workflow_fix_updates_project_yaml(gates):
    _with_workflow(gates)
    hid = _workflow_heal(gates, "text=Mark verified {app_id}")
    r = _decide(gates, hid, "approve", "the button was renamed")
    assert r.json()["data"]["note"] == "project.yaml updated"
    text = gates.project.config_path.read_text(encoding="utf-8")
    assert yaml.safe_load(text)["workflows"][0]["steps"][0]["click"] == "text=Mark verified {app_id}"
    assert "# the clerk's button" in text
    assert _case_params(gates, "TC-0190")["steps"][0]["click"] == "text=Mark verified {app_id}"


def test_a_hostile_value_from_the_tested_site_still_leaves_valid_yaml_with_nothing_else_changed(gates):
    _with_workflow(gates)
    before = yaml.safe_load(gates.project.config_path.read_text(encoding="utf-8"))
    hostile = 'Mark" verified\nproject: Hijacked\n  - : x'
    hid = _workflow_heal(gates, hostile)
    assert _decide(gates, hid, "approve", "renamed").json()["data"]["note"] == "project.yaml updated"
    after = yaml.safe_load(gates.project.config_path.read_text(encoding="utf-8"))
    before["workflows"][0]["steps"][0]["click"] = hostile
    assert after == before


def test_only_a_proposed_locator_or_workflow_fix_is_decided_and_never_while_a_run_goes(gates):
    assert _decide(gates, _heal(gates, status="approved"), "approve").status_code == 409
    assert _decide(gates, _heal(gates, kind="manual", new={}), "approve").status_code == 409
    assert _decide(gates, 999_999, "approve").status_code == 404
    assert gates.client.post(f"{gates.base}/heals/0", json={"decision": "approve"}, headers=CSRF).status_code == 422
    hid = _heal(gates)
    gates.busy()
    assert _decide(gates, hid, "approve").status_code == 409
    assert _decide(gates, hid, "apply").status_code == 422


def test_a_double_click_applies_a_fix_once(gates, monkeypatch):
    import threading
    import time as _time

    from agentqa.agents import healer
    hid = _heal(gates)
    calls = []
    real = healer.approve_heal

    def slow(*a, **kw):
        calls.append(1)
        _time.sleep(0.3)
        return real(*a, **kw)
    monkeypatch.setattr(healer, "approve_heal", slow)
    codes: list[int] = []
    threads = [threading.Thread(target=lambda: codes.append(_decide(gates, hid, "approve").status_code))
               for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sorted(codes) == [200, 409] and len(calls) == 1


def test_long_text_from_the_engine_is_capped(gates):
    with gates.db() as s:
        hid = s.insert("heals", {"case_id": "TC-" + "9" * 400, "run_id": "r", "kind": "manual", "old": {}, "new": {},
                                 "reason": "r" * 3000, "status": "proposed", "created_at": "2026-11-05T10:00:00"})
    h = next(x for x in gates.client.get(f"{gates.base}/heals").json()["data"]["items"] if x["id"] == hid)
    assert len(h["reason"]) == 1000 and len(h["case_id"]) == 200


def test_a_locator_fix_that_cannot_reach_project_yaml_says_so(gates):
    with gates.db() as s:
        s.exec("UPDATE cases SET type='workflow', params=? WHERE id='TC-0190'",
               ['{"workflow_id": "WF-09", "steps": [{"role": "citizen", "fill": {"mobile": "{mobile}"}}]}'])
    note = _decide(gates, _heal(gates), "approve").json()["data"]["note"]
    assert note == "Could not rename 'mobile' in project.yaml: change it there by hand"


def test_a_workflow_fix_changes_its_own_step_only(gates):
    path = gates.project.config_path
    two = WORKFLOW + """      - role: clerk
        click: "text=Verify {app_id}"
"""
    path.write_text(path.read_text(encoding="utf-8").replace("workflows: []\n", two), encoding="utf-8")
    hid = _heal(gates, kind="workflow", old={"workflow": "WF-01", "step": 2, "key": "click",
                                             "value": "text=Verify {app_id}"},
                new={"value": "text=Mark verified {app_id}"})
    assert _decide(gates, hid, "approve", "renamed").json()["data"]["note"] == "project.yaml updated"
    steps = yaml.safe_load(path.read_text(encoding="utf-8"))["workflows"][0]["steps"]
    assert [s["click"] for s in steps] == ["text=Verify {app_id}", "text=Mark verified {app_id}"]
