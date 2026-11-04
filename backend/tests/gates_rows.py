"""Row builders for the gate tests (M1.4): the smallest rows the engine accepts for questions, cases, imported manual
cases, defects, heals and requirements, each overridable field by field."""
from __future__ import annotations

from agentqa.store import Store

AT = "2026-11-04T10:00:00"


def question(s: Store, n: int, **over) -> int:
    row = {"key": f"q:{n}", "rule_id": f"R-{n:03d}", "req_id": f"FR-{n:02d}", "kind": "divergence",
           "question": f"Question {n}?", "options": ["SRS is correct (the app has a defect)", "App is correct (update the SRS)",
                                                     "Neither: I will enter the correct value"],
           "proposed": None, "priority": "Medium", "status": "open", "context": None, **over}
    return s.insert("questions", row)


def case(s: Store, n: int, **over) -> str:
    cid = over.pop("id", f"TC-{n:04d}")
    s.insert("cases", {"id": cid, "key": f"k:{n}", "seq": n, "type": "functional", "title": f"Case {n}", "role": "citizen",
                       "path": "/apply", "params": {}, "rule_ids": [], "req_ids": [f"FR-{n:02d}"], "priority": "P2",
                       "oracle_source": "srs", "status": "proposed", "created_at": AT, **over})
    return cid


def manual(s: Store, n: int, **over) -> str:
    mid = over.pop("id", f"MT-{n:03d}")
    s.insert("manual_cases", {"id": mid, "title": f"Manual {n}", "role": "citizen", "steps": "Open /apply",
                              "expected": "It opens", "converted": {"coverage": 1.0}, "coverage": 1.0, "status": "ready",
                              "source_file": "manual_tests.xlsx", "created_at": AT, **over})
    return mid


def defect(s: Store, n: int, **over) -> str:
    did = over.pop("id", f"DEF-{n:03d}")
    s.insert("defects", {"id": did, "seq": n, "run_id": "R-1", "case_ids": [f"TC-{n:04d}"], "signature": f"sig:{n}",
                         "title": f"Defect {n}", "severity": "High", "priority": "P1", "role": "citizen",
                         "url": "http://127.0.0.1:8800/apply", "steps": "1. Open /apply", "expected": "Rejected",
                         "actual": "Accepted", "evidence": [], "rule_ids": [], "req_ids": [f"FR-{n:02d}"],
                         "status": "draft", "created_at": AT, "notes": "", **over})
    return did


def heal(s: Store, **over) -> int:
    row = {"case_id": "TC-0001", "run_id": "R-1", "kind": "locator",
           "old": {"field": "mobile", "label": "Mobile", "path": "/apply"},
           "new": {"field": "mobile_no", "label": "Mobile Number"}, "reason": "the field was renamed",
           "status": "proposed", "created_at": AT, **over}
    return s.insert("heals", row)


def requirement(s: Store, n: int, **over) -> str:
    rid = over.pop("id", f"FR-{n:02d}")
    s.insert("requirements", {"id": rid, "seq": n, "section": "Apply", "text": f"Requirement {n}.", "kind": "functional",
                              "priority": "M", "roles": ["citizen"], "ambiguity": [], "source_file": "Demo.docx",
                              "disposition": "gap", "disposition_note": "no test case traces to it yet", **over})
    return rid
