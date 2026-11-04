"""M1.4: what is waiting for a person (the navigation badges, the Project page, the Live View), and the change log
page, newest first."""
from __future__ import annotations

from agentqa import assist
from agentqa.orchestrator.gates import changelog
from conftest import CSRF, GATES_WHO


def _gates(g) -> dict:
    r = g.client.get(f"{g.base}/gates")
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_the_counts_are_the_fixtures(gates):
    data = _gates(gates)
    assert data["questions_open"] == 15
    assert data["plan"]["exists"] is True and data["plan"]["approved"] is True
    assert data["plan"]["cases"] == 206 and data["plan"]["proposed"] == 0 and len(data["plan"]["digest"]) == 12
    assert data["imported_ready"] == 0
    assert data["defects_draft"] == 19 and data["defects_open"] == 19
    assert data["visual_changed"] == 0 and data["heals_proposed"] == 0 and data["assist_pending"] == 0
    assert data["paused"] is False and data["running"] is False


def test_the_counts_follow_what_happens(gates):
    with gates.db() as s:
        s.exec("UPDATE cases SET status='proposed' WHERE type='functional'")
        s.exec("UPDATE plan SET approved=0")
        s.exec("UPDATE visual SET status='changed' WHERE rowid IN (SELECT rowid FROM visual LIMIT 2)")
        s.insert("assist", {"at": "2026-11-04T10:00:00", "kind": "otp", "role": "citizen", "agent": "explorer",
                            "question": "Type the OTP", "status": "pending"})
    assist.request_pause(gates.project, by=GATES_WHO)
    gates.busy()
    data = _gates(gates)
    assert data["plan"]["approved"] is False and data["plan"]["proposed"] == 56
    assert data["visual_changed"] == 2 and data["assist_pending"] == 1
    assert data["paused"] is True and data["running"] is True


def test_a_project_with_no_run_yet_has_nothing_waiting(gates):
    gates.client.post("/api/v1/projects", json={"name": "Empty", "url": "https://uat.example.gov.in"}, headers=CSRF)
    data = gates.client.get("/api/v1/projects/empty/gates").json()["data"]
    assert data["plan"] == {"exists": False, "approved": False, "proposed": 0, "cases": 0, "digest": None}
    assert data["questions_open"] == 0 and data["defects_open"] == 0


def test_the_change_log_pages_newest_first(gates):
    with gates.db() as s:
        ids = [changelog.record(s, "case", f"TC-{n:04d}", f"change {n}", f"why {n}", GATES_WHO) for n in range(1, 6)]
    r = gates.client.get(f"{gates.base}/changes", params={"limit": 2})
    data = r.json()["data"]
    assert [x["id"] for x in data["items"]] == [ids[4], ids[3]] and data["next_before"] == ids[3]
    assert data["items"][0]["why"] == "why 5" and data["items"][0]["by"] == GATES_WHO
    older = gates.client.get(f"{gates.base}/changes", params={"limit": 2, "before": data["next_before"]}).json()["data"]
    assert [x["id"] for x in older["items"]] == [ids[2], ids[1]]
    assert gates.client.get(f"{gates.base}/changes", params={"limit": 201}).status_code == 422
    assert gates.client.get(f"{gates.base}/changes", params={"before": 0}).status_code == 422


def test_a_viewer_reads_the_summary_and_the_change_log(gates):
    viewer = gates.as_role("viewer")
    assert viewer.get(f"{gates.base}/gates").status_code == 200
    assert viewer.get(f"{gates.base}/changes").status_code == 200
