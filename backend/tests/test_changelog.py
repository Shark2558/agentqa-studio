"""M1.4 Phase A: the change log knows who and why (FR-ACC-3). `who` names the signed-in person, `record` writes a
person's row, `page` reads the log newest first; the engine's own writers take `by=` and default to "dashboard"."""
from __future__ import annotations

import pytest

from agentqa.agents import healer, reconciler, requirements
from agentqa.api.auth import User
from agentqa.orchestrator.gates import changelog
from gates_rows import case, heal, question, requirement

WHO = "owner@example.com (owner)"


def test_who_is_the_email_and_the_role():
    assert changelog.who(User("owner@example.com", "owner")) == WHO
    assert changelog.who(User("t@example.com", "tester")) == "t@example.com (tester)"


def test_a_record_is_a_persons_row_with_who_and_why(demo):
    _, s = demo
    rid = changelog.record(s, "plan", "-", "approved the plan: 3 approved, 1 rejected", "  looks right  ", WHO)
    row = s.one("SELECT * FROM change_log WHERE id=?", [rid])
    assert (row["agent"], row["object"], row["object_id"], row["by"]) == ("person", "plan", "-", WHO)
    assert row["change"] == "approved the plan: 3 approved, 1 rejected" and row["justification"] == "looks right"
    assert row["at"]


def test_a_reason_is_trimmed_and_cut_to_500_characters(demo):
    _, s = demo
    rid = changelog.record(s, "defect", "DEF-001", "rejected", "x" * 900, WHO)
    assert len(s.one("SELECT justification FROM change_log WHERE id=?", [rid])["justification"]) == changelog.WHY_MAX
    assert changelog.clean_why(None) == "" and changelog.clean_why("  a \n") == "a"


def test_a_long_change_is_cut(demo):
    _, s = demo
    rid = changelog.record(s, "case", "TC-0001", "y" * 5000, "", WHO)
    assert len(s.one("SELECT change FROM change_log WHERE id=?", [rid])["change"]) == changelog.CHANGE_MAX


def test_the_log_pages_newest_first_with_before(demo):
    _, s = demo
    ids = [changelog.record(s, "case", f"TC-{n:04d}", f"change {n}", f"why {n}", WHO) for n in range(1, 6)]
    first = changelog.page(s, limit=2)
    assert [r["id"] for r in first["items"]] == [ids[4], ids[3]] and first["next_before"] == ids[3]
    assert set(first["items"][0]) == {"id", "at", "agent", "object", "object_id", "change", "why", "by"}
    assert first["items"][0]["why"] == "why 5" and first["items"][0]["by"] == WHO
    second = changelog.page(s, limit=2, before=first["next_before"])
    assert [r["id"] for r in second["items"]] == [ids[2], ids[1]]
    last = changelog.page(s, limit=2, before=second["next_before"])
    assert [r["id"] for r in last["items"]] == [ids[0]] and last["next_before"] is None


def test_a_page_is_at_most_200_rows(demo):
    _, s = demo
    for n in range(205):
        changelog.record(s, "case", str(n), "c", "", WHO)
    assert len(changelog.page(s, limit=1000)["items"]) == changelog.PAGE_MAX


def test_the_last_row_for_an_object_names_who_did_it(demo):
    _, s = demo
    changelog.record(s, "plan", "-", "approved the plan: 1 approved, 0 rejected", "", "a@example.com (owner)")
    changelog.record(s, "plan", "-", "asked to re-plan with 2 answered question(s)", "", "b@example.com (tester)")
    assert changelog.last(s, "plan", "approved the plan")["by"] == "a@example.com (owner)"
    assert changelog.last(s, "plan", "nothing like this") is None


# ---- the engine's own writers take `by=` --------------------------------------------------------

@pytest.mark.parametrize("by", [None, WHO])
def test_answer_question_logs_by(demo, by):
    _, s = demo
    qid = question(s, 1)
    reconciler.answer_question(s, qid, 0, **({"by": by} if by else {}))
    assert s.one("SELECT by FROM change_log")["by"] == (by or "dashboard")


@pytest.mark.parametrize("by", [None, WHO])
def test_approve_heal_logs_by(demo, by):
    p, s = demo
    case(s, 1, params={"field": "mobile"})
    hid = heal(s)
    healer.approve_heal(s, hid, project=p, **({"by": by} if by else {}))
    assert s.one("SELECT by FROM change_log")["by"] == (by or "dashboard")


@pytest.mark.parametrize("by", [None, WHO])
def test_set_disposition_logs_by(demo, by):
    _, s = demo
    requirement(s, 1)
    requirements.set_disposition(s, "FR-01", "manual", "by hand", **({"by": by} if by else {}))
    assert s.one("SELECT by FROM change_log")["by"] == (by or "dashboard")
