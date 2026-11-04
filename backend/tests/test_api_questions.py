"""M1.4 Gate 1 — questions: list, answer in plain English (with a value only when the option asks for one), reopen with
a reason, and "Apply my answers and re-plan". Every decision is logged with the signed-in person."""
from __future__ import annotations

import json

import pytest

from agentqa import replan
from agentqa.agents import reconciler
from agentqa.orchestrator.gates import questions
from conftest import CSRF, GATES_WHO

PRIORITY = {"High": 0, "Medium": 1, "Low": 2}


def _list(g, **params) -> dict:
    r = g.client.get(f"{g.base}/questions", params=params)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _open_of(g, kind: str) -> dict:
    return next(q for q in _list(g, status="open")["items"] if q["kind"] == kind)


def _answer(g, qid: int, choice: int, value: str = ""):
    return g.client.post(f"{g.base}/questions/{qid}/answer", json={"choice": choice, "value": value}, headers=CSRF)


def test_the_list_puts_open_questions_first_by_priority_with_counts(gates):
    data = _list(gates)
    assert data["counts"] == {"open": 15, "answered": 0} and data["total"] == 15
    keys = [(PRIORITY.get(q["priority"], 2), q["id"]) for q in data["items"]]
    assert keys == sorted(keys)
    q = data["items"][0]
    assert set(q) >= {"id", "kind", "question", "options", "proposed", "priority", "req_id", "rule_id", "status", "answer",
                      "value", "answered_at"}
    assert all(set(o) == {"label", "needs_value"} for o in q["options"])
    assert "context" not in q and "key" not in q


def test_the_list_says_which_policy_a_replan_will_use(gates):
    """'Apply my answers' reconciles with the rule the last run used, else project.yaml's: the page must say which."""
    assert _list(gates)["policy"] == {"divergence": "ask", "inferred_access": "ask", "source": "project"}
    with gates.db() as s:
        s.set_meta(replan.POLICY_KEY, "srs_wins")                  # a run started with --policy srs_wins
    assert _list(gates)["policy"] == {"divergence": "srs_wins", "inferred_access": "ask", "source": "run"}


@pytest.mark.parametrize("cfg, remembered, expected", [
    ({"policy": None}, None, ("ask", "ask", "project")),                       # `policy:` left empty in project.yaml
    ({"policy": {"divergence": "srs_wins", "inferred_access": "deny"}}, None, ("srs_wins", "deny", "project")),
    ({"policy": {"divergence": "<b>x</b>" * 50, "inferred_access": 3}}, None, ("ask", "ask", "project")),   # unknown: "ask"
    ({"policy": {"divergence": "ask"}}, "app_wins", ("app_wins", "ask", "run")),
    ({"policy": {"divergence": "ask"}}, "<script>", ("ask", "ask", "project")),     # a junk remembered value is ignored
])
def test_the_policy_is_read_safely(cfg, remembered, expected):
    from types import SimpleNamespace
    got = questions.policy(SimpleNamespace(cfg=cfg), SimpleNamespace(get_meta=lambda key, default=None: remembered))
    assert (got["divergence"], got["inferred_access"], got["source"]) == expected


def test_the_list_filters_by_status_and_pages(gates):
    first = _open_of(gates, "app_only")
    assert _answer(gates, first["id"], 0).status_code == 200
    assert _list(gates, status="answered")["counts"] == {"open": 14, "answered": 1}
    assert [q["id"] for q in _list(gates, status="answered")["items"]] == [first["id"]]
    page = _list(gates, status="open", limit=5, offset=5)
    assert len(page["items"]) == 5 and page["total"] == 14
    assert gates.client.get(f"{gates.base}/questions", params={"limit": 201}).status_code == 422
    assert gates.client.get(f"{gates.base}/questions", params={"status": "closed"}).status_code == 422


def test_an_answer_is_logged_with_the_signed_in_person(gates):
    q = _open_of(gates, "inferred_access")
    r = _answer(gates, q["id"], 0)
    assert r.status_code == 200
    item = r.json()["data"]
    assert item["status"] == "answered" and item["answer"] == reconciler.OPTIONS["inferred_access"][0]
    with gates.db() as s:
        row = s.one("SELECT * FROM change_log WHERE object='question' ORDER BY id DESC LIMIT 1")
    assert row["by"] == GATES_WHO and row["object_id"] == str(q["id"])


def test_an_option_that_asks_for_a_value_needs_one(gates):
    q = _open_of(gates, "ambiguous")
    assert [o["needs_value"] for o in q["options"]] == [False, True, False]
    r = _answer(gates, q["id"], 1, "   ")
    assert r.status_code == 422 and "value" in r.json()["error"]["message"].lower()
    r = _answer(gates, q["id"], 1, "at most 10 digits")
    assert r.status_code == 200 and r.json()["data"]["value"] == "at most 10 digits"
    with gates.db() as s:
        stored = s.one("SELECT answer_value FROM questions WHERE id=?", [q["id"]])["answer_value"]
    assert json.loads(stored) == {"choice": 1, "value": "at most 10 digits"}


def test_a_value_for_an_option_that_does_not_ask_for_one_is_not_kept(gates):
    q = _open_of(gates, "ambiguous")
    assert _answer(gates, q["id"], 0, "ignored").json()["data"]["value"] == ""


def test_a_wrong_choice_an_answered_question_and_an_unknown_one_are_refused(gates):
    q = _open_of(gates, "workflow")
    assert _answer(gates, q["id"], 2).status_code == 422                      # a workflow question has two options
    assert _answer(gates, q["id"], -1).status_code == 422
    assert _answer(gates, q["id"], 0).status_code == 200
    again = _answer(gates, q["id"], 1)
    assert again.status_code == 409 and again.json()["error"]["code"] == "not_open"
    assert _answer(gates, 99_999, 0).status_code == 404
    r = gates.client.post(f"{gates.base}/questions/{q['id']}/answer", json={"choice": 0, "value": "x" * 401}, headers=CSRF)
    assert r.status_code == 422


def test_reopening_needs_a_reason_and_is_logged(gates):
    q = _open_of(gates, "srs_only_field")
    url = f"{gates.base}/questions/{q['id']}/reopen"
    assert gates.client.post(url, json={"why": "changed my mind"}, headers=CSRF).status_code == 409   # still open
    _answer(gates, q["id"], 0)
    assert gates.client.post(url, json={"why": "  "}, headers=CSRF).status_code == 422
    assert gates.client.post(url, json={}, headers=CSRF).status_code == 422
    r = gates.client.post(url, json={"why": "the portal team says it exists"}, headers=CSRF)
    assert r.status_code == 200 and r.json()["data"]["status"] == "open" and r.json()["data"]["answer"] is None
    with gates.db() as s:
        row = s.one("SELECT * FROM change_log ORDER BY id DESC LIMIT 1")
    label = reconciler.OPTIONS["srs_only_field"][0]
    assert row["change"] == f"reopened (was '{label}')" and row["justification"] == "the portal team says it exists"
    assert row["by"] == GATES_WHO and row["object"] == "question"


def test_the_value_table_matches_the_reconcilers_options():
    asks = {(kind, i) for kind, opts in reconciler.OPTIONS.items() for i, o in enumerate(opts) if "enter" in o.lower()}
    assert asks == {(kind, i) for kind, idx in questions.VALUE_OPTIONS.items() for i in idx}
    assert set(questions.VALUE_OPTIONS) <= set(reconciler.OPTIONS)


def test_apply_starts_a_replan_and_logs_it(gates):
    _answer(gates, _open_of(gates, "app_only")["id"], 0)
    _answer(gates, _open_of(gates, "workflow")["id"], 1)
    r = gates.client.post(f"{gates.base}/questions/apply", json={}, headers=CSRF)
    assert r.status_code == 202 and r.json()["data"]["stage"] == "replan"
    assert gates.spawned == [(["replan"], "replan")]
    with gates.db() as s:
        row = s.one("SELECT * FROM change_log ORDER BY id DESC LIMIT 1")
    assert row["change"] == "asked to re-plan with 2 answered question(s)" and row["by"] == GATES_WHO
    again = gates.client.post(f"{gates.base}/questions/apply", json={}, headers=CSRF)
    assert again.status_code == 409 and again.json()["error"]["code"] == "busy"


def test_a_viewer_reads_questions_but_cannot_answer(gates):
    viewer = gates.as_role("viewer")
    assert viewer.get(f"{gates.base}/questions").status_code == 200
    q = _open_of(gates, "app_only")
    r = viewer.post(f"{gates.base}/questions/{q['id']}/answer", json={"choice": 0}, headers=CSRF)
    assert r.status_code == 403 and r.json()["error"]["code"] == "read_only"


def test_an_id_too_large_for_the_database_is_not_found_not_a_crash(gates):
    for qid in ("99999999999999999999", "0"):
        r = gates.client.post(f"{gates.base}/questions/{qid}/answer", json={"choice": 0}, headers=CSRF)
        assert r.status_code in (404, 422), (qid, r.status_code)
    assert gates.client.get(f"{gates.base}/changes", params={"before": 10 ** 20}).status_code == 422


def test_a_reopened_question_shows_no_answer_time(gates):
    q = _open_of(gates, "srs_only_feature")
    _answer(gates, q["id"], 0)
    r = gates.client.post(f"{gates.base}/questions/{q['id']}/reopen", json={"why": "ask the team"}, headers=CSRF)
    assert r.json()["data"]["answered_at"] is None and r.json()["data"]["choice"] is None
