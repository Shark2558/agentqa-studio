from agentqa import readiness
from agentqa.agents import assistant


def _run(s, results):
    s.insert("runs", {"id": "run-1", "started_at": "2026-10-30T10:00:00", "status": "done", "total": len(results),
                      "passed": sum(1 for r in results if r[2] == "pass")})
    for cid, pri, cat in results:
        s.insert("cases", {"id": cid, "seq": int(cid[-2:]), "type": "page_smoke", "title": cid, "priority": pri,
                           "role": "citizen", "status": "approved", "req_ids": ["FR-01"]})
        s.insert("results", {"run_id": "run-1", "case_id": cid, "outcome": "passed" if cat == "pass" else "failed",
                             "category": cat, "message": "", "evidence": []})
    s.set_meta("last_run", "run-1")


def test_critical_defect_blocks_the_release(demo):
    p, s = demo
    _run(s, [("TC-01", "P1", "pass"), ("TC-02", "P1", "pass"), ("TC-03", "P3", "defect")])
    s.insert("requirements", {"id": "FR-01", "seq": 1, "text": "x"})
    s.insert("defects", {"id": "DEF-001", "seq": 1, "signature": "a", "title": "t", "severity": "Critical", "status": "draft"})
    r = readiness.compute(p, s)
    assert r["verdict"] == "Not ready" and any("block" in x for x in r["reasons"])
    s.update("defects", "id", "DEF-001", {"status": "resolved"})
    r = readiness.compute(p, s)
    assert r["score"] >= 85 and r["verdict"] == "Ready"


def test_assistant_routes_questions_and_commands(explored):
    p, s = explored
    _run(s, [("TC-01", "P1", "pass"), ("TC-02", "P2", "defect")])
    assert "readiness" in assistant.answer(p, s, "How ready is this release?")["text"].lower()
    failed = assistant.answer(p, s, "What failed in the last run?")
    assert "did not pass" in failed["text"] and failed["actions"][0]["kind"] == "run"
    rerun = assistant.answer(p, s, "Re-run the failed tests")
    assert rerun["actions"] and rerun["actions"][0]["only"] == ["TC-02"]
    added = assistant.answer(p, s, "Add a test that clerk cannot open /admin/users")
    assert added["text"].startswith("Added CHAT-")
    assert s.one("SELECT * FROM manual_cases WHERE id LIKE 'CHAT-%'")["status"] == "approved"
