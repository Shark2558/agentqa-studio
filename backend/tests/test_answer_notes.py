"""M1.4 sitting 1, finding S1 (the owner's decision, 4 Nov 2026: honest words now, real later). An answer to "A vague
requirement" or to a contradiction is a note for checking by hand: no stage reads it yet. The questions API says so
(`note_only`); the Requirements stage keeps such a requirement "Not testable" (AgentQA cannot test it yet; "manual"
reads as "tested by hand" and no one has) with the answer in its note, and the report shows that note instead of
"waiting for a person". Also S3: an answer's change-log row names the page it is about instead of "the plan"."""
from __future__ import annotations

from pathlib import Path

import pytest

from agentqa.agents import reconciler, reporter, requirements
from agentqa.orchestrator.gates import questions
from conftest import CSRF

RULE = "Every page loads within 3 seconds on the test environment."
CONTRA = {"kind": "max_length", "field": "remarks", "values": {'{"max": 100}': ["FR-20"], '{"max": 50}': ["FR-21"]},
          "reqs": ["FR-20", "FR-21"]}


def _questions(g) -> list[dict]:
    r = g.client.get(f"{g.base}/questions")
    assert r.status_code == 200, r.text
    return r.json()["data"]["items"]


def _vague(g, req_id: str) -> dict:
    return next(q for q in _questions(g) if q["question"].startswith(f"{req_id} is not testable"))


def _answer(g, req_id: str, choice: int = 1, value: str = RULE) -> dict:
    q = _vague(g, req_id)
    r = g.client.post(f"{g.base}/questions/{q['id']}/answer", json={"choice": choice, "value": value}, headers=CSRF)
    assert r.status_code == 200, r.text
    return q


def _check_and_get(g, rid: str) -> dict:
    with g.db() as store:
        requirements.check(g.project, store)
    r = g.client.get(f"{g.base}/requirements")
    assert r.status_code == 200, r.text
    return next(x for x in r.json()["data"]["requirements"] if x["id"] == rid)


# ---- the API ------------------------------------------------------------------------------------------------------

def test_only_answers_no_stage_reads_are_marked_note_only(gates):
    items = _questions(gates)
    assert {q["req_id"] for q in items if q["note_only"]} == {"FR-12", "NFR-01", "NFR-04"}
    tbd = next(q for q in items if q["question"].startswith("FR-13: the value for"))
    assert tbd["kind"] == "ambiguous" and tbd["note_only"] is False      # a TBD value does become a rule
    assert all(isinstance(q["note_only"], bool) for q in items)


# ---- the Requirements stage, through the fixture ---------------------------------------------------------------------

def test_an_answered_vague_requirement_reads_as_a_hand_check_with_the_answer(gates):
    _answer(gates, "NFR-01")
    nfr01 = _check_and_get(gates, "NFR-01")
    assert nfr01["disposition"] == "not_testable"
    assert RULE in nfr01["disposition_note"] and "by hand" in nfr01["disposition_note"]
    assert _check_and_get(gates, "NFR-04")["disposition"] == "clarify"      # still open: unchanged


def test_not_testable_stays_not_testable_with_the_answer(gates):
    _answer(gates, "NFR-01", choice=2, value="")
    nfr01 = _check_and_get(gates, "NFR-01")
    assert nfr01["disposition"] == "not_testable" and "Not testable" in nfr01["disposition_note"]


def test_tests_and_a_person_s_disposition_still_win_over_an_answer(gates):
    _answer(gates, "FR-12", choice=0, value="")
    assert _check_and_get(gates, "FR-12")["disposition"] == "covered"
    r = gates.client.patch(f"{gates.base}/requirements/NFR-01", json={"disposition": "out_of_scope", "why": "next release"},
                           headers=CSRF)
    assert r.status_code == 200, r.text
    _answer(gates, "NFR-01")
    assert _check_and_get(gates, "NFR-01")["disposition"] == "out_of_scope"


def test_a_reopened_answer_is_no_longer_a_note(gates):
    q = _answer(gates, "NFR-01")
    with gates.db() as store:
        questions.reopen(store, q["id"], "ask the department", "tester")
    assert _check_and_get(gates, "NFR-01")["disposition"] == "clarify"


def test_answers_that_change_the_plan_are_not_notes(gates):
    with gates.db() as store:
        tbd = store.one("SELECT id FROM questions WHERE key LIKE 'tbd:%'")
        reconciler.answer_question(store, tbd["id"], 1, "max 250 characters", by="tester")
        assert requirements.answered_notes(store) == {}


def test_the_report_shows_the_stored_hand_check_instead_of_waiting_for_a_person(gates):
    _answer(gates, "NFR-01")
    with gates.db() as store:
        requirements.check(gates.project, store)
        out = reporter.report(gates.project, store)
    html = Path(out["report"]).read_text(encoding="utf-8")
    nfr01 = html[html.index("<td>NFR-01</td>"):]
    nfr01 = nfr01[:nfr01.index("</tr>")]
    assert RULE in nfr01 and "by hand" in nfr01 and "waiting for a person" not in nfr01


# ---- the disposition rule, one requirement at a time --------------------------------------------------------------

def _decide(req: dict, answered: dict, contradictions=(), rules=()) -> tuple[str, str] | None:
    return requirements.answered_disposition(req, {"contradictions": list(contradictions)}, list(rules), answered)


def test_an_answered_contradiction_reaches_every_requirement_in_it():
    answered = {requirements.contradiction_key(CONTRA): "Use the proposed interpretation (manual check)"}
    for rid in CONTRA["reqs"]:
        disp, note = _decide({"id": rid, "ambiguity": []}, answered, [CONTRA])
        assert disp == "not_testable" and "proposed interpretation" in note


def test_an_unanswered_contradiction_or_an_unresolved_rule_keeps_the_requirement_open():
    vague = {requirements.vague_key("FR-21"): "Enter a precise rule: 50"}
    req = {"id": "FR-21", "ambiguity": [{"term": "appropriate"}]}
    assert _decide(req, vague, [CONTRA]) is None
    assert _decide(req, vague, [], [{"status": "Ambiguous"}]) is None
    assert _decide(req, vague)[0] == "not_testable"


def test_a_stale_vague_answer_does_not_count_and_several_answers_are_all_kept():
    stale = {requirements.vague_key("FR-21"): "Enter a precise rule: 50"}
    assert _decide({"id": "FR-21", "ambiguity": []}, stale) is None
    both = {**stale, requirements.contradiction_key(CONTRA): "Use the proposed interpretation (manual check)"}
    disp, note = _decide({"id": "FR-21", "ambiguity": [{"term": "x"}]}, both, [CONTRA])
    assert disp == "not_testable" and "50" in note and "proposed interpretation" in note


@pytest.mark.parametrize("raw", ["[1]", "null", "5", '"s"', "{bad", None])
def test_a_damaged_answer_value_reads_as_no_choice(raw):
    assert reconciler._choice({"answer_value": raw}) == (-1, "")


# ---- the change log (S3) ------------------------------------------------------------------------------------------

def test_note_only_needs_a_note_only_key():
    assert requirements.note_only("contradiction:max_length:remarks") and requirements.note_only("ambiguous:FR-12")
    assert not any(requirements.note_only(k) for k in (None, "", "tbd:remarks", "divergence:x"))


def test_an_answer_about_a_page_names_the_page_not_the_plan(gates):
    with gates.db() as store:
        q = store.one("SELECT id FROM questions WHERE key='inferred_access:/apply'")
        reconciler.answer_question(store, q["id"], 0, by="tester")
        row = store.one("SELECT change FROM change_log ORDER BY id DESC LIMIT 1")
    assert row["change"] == "answered 'Yes: block these roles' for /apply"
