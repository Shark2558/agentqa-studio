"""The Requirement Chat agent: typed English → candidate requirements + at most five clarifying questions."""
from __future__ import annotations

import pytest

from agentqa.agents import req_chat
from agentqa.config import Project, init_project

TYPED = """\
The portal lets citizens apply for a birth certificate.
- The applicant must upload an ID proof (PDF or JPG, maximum size).
- Clerks shall verify the application within 2 working days.
1. The system should send an SMS when the certificate is ready.
As a citizen, I want to download my certificate so that I do not need to visit the office.
Scenario: Expired OTP
  Given a citizen requested an OTP
  When 5 minutes pass
  Then the OTP must be rejected
The page must load quickly.
"""


@pytest.fixture
def project(tmp_path):
    init_project(tmp_path / "p", "Portal", "https://portal.example")
    return Project(tmp_path / "p")


def test_bullets_numbers_sentences_stories_and_gherkin_each_become_a_requirement():
    items = req_chat.extract(TYPED)
    texts = [i["text"] for i in items]
    assert any(t.startswith("The applicant must upload") for t in texts)          # bullet
    assert any(t.startswith("The system should send an SMS") for t in texts)      # numbered
    assert any(t.startswith("Clerks shall verify") for t in texts)                # bullet with a modal verb
    assert any(t.startswith("As a citizen, I want") for t in texts)               # user story
    story = next(i for i in items if i["text"].startswith("As a citizen"))
    assert story["kind"] == "story"
    scenario = next(i for i in items if i["kind"] == "gherkin")
    assert "Given a citizen requested an OTP" in scenario["text"] and "Then the OTP must be rejected" in scenario["text"]
    assert "The portal lets citizens apply" in texts[0]                           # a plain statement still counts
    assert [i["id"] for i in items] == [f"T-{n:03d}" for n in range(1, len(items) + 1)]


def test_vague_words_are_flagged_with_the_analysts_reason():
    items = req_chat.extract("The page must load quickly.")
    assert items[0]["flags"] == [{"word": "quickly", "why": "no measurable time limit"}]


def test_questions_cover_roles_limits_failures_login_and_vague_words_and_stop_at_five(project):
    text = "Reports can be exported. The export must finish within a reasonable time. Files up to the maximum size are accepted. It must be quick. It should be easy."
    qs = req_chat.questions(text, req_chat.extract(text), project.role_aliases())
    topics = [q["topic"] for q in qs]
    assert topics[:4] == ["roles", "limit", "failure", "login"]
    assert len(qs) == 5 and qs[4]["topic"] == "vague"
    assert "within" in qs[1]["question"]                     # the first limit word in the text, quoted back


def test_no_questions_when_the_text_already_answers_them(project):
    text = ("Citizens sign in with a mobile OTP. A citizen can upload a PDF of at most 2 MB; "
            "if the file is larger the portal rejects it with an error message.")
    assert req_chat.questions(text, req_chat.extract(text), project.role_aliases()) == []


def test_the_rule_path_is_used_when_ai_is_off(project):
    out = req_chat.chat(project, TYPED)
    assert out["source"] == "rules" and len(out["items"]) >= 6 and 1 <= len(out["questions"]) <= 5


class FakeGateway:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def available(self):
        return True

    def complete_json(self, system, user, **kw):
        self.calls.append((system, user, kw))
        return self.answer


def test_the_ai_path_is_used_when_the_project_allows_it_and_marks_its_output(project):
    project.cfg["ai"] = {"mode": "cloud"}
    gw = FakeGateway({"requirements": [{"text": "Citizens can apply online."}, {"text": "Clerks verify within 2 days."}],
                      "questions": ["Which ID proofs are accepted?"]})
    out = req_chat.chat(project, TYPED, gateway=gw)
    assert out["source"] == "ai" and [i["text"] for i in out["items"]] == ["Citizens can apply online.", "Clerks verify within 2 days."]
    assert out["questions"] == [{"id": "q1", "topic": "ai", "question": "Which ID proofs are accepted?"}]
    assert gw.calls[0][2]["task"] == "req_chat" and TYPED.strip() in gw.calls[0][1]


def test_the_ai_path_falls_back_to_rules_when_the_model_gives_nothing(project):
    project.cfg["ai"] = {"mode": "cloud"}
    out = req_chat.chat(project, TYPED, gateway=FakeGateway(None))
    assert out["source"] == "rules" and len(out["items"]) >= 6
