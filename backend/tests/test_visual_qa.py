"""Requirement 5: the Visual QA agent acts only on controls it was shown and passes only with a quote from the page.

Runs a real browser against the demo Citizen Portal. The "model" is the local AI stand-in (demo/mock_ai.py),
which answers AgentQA's tagged tasks by word overlap: it exercises the plumbing (gateway, grounding, quote
check), not a model's judgement.
"""
from __future__ import annotations

import threading
import time

import pytest
from cryptography.fernet import Fernet

from conftest import free_port

from demo import mock_ai

pw = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def portal():
    import uvicorn
    from demo.portal.app import citizen_portal
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(citizen_portal, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True


@pytest.fixture
def browser_page():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        yield page
        b.close()


@pytest.fixture
def ai(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AGENTQA_VAULT_KEY", Fernet.generate_key().decode())
    port = free_port()
    srv = mock_ai.serve(port)
    from agentqa.ai import gateway
    gw = gateway()
    gw.store.set_policy({"order": ["openai"], "timeout_s": 5, "backoff_s": 0.05})

    def add(key):
        for k in gw.store.keys():
            gw.store.delete_key(k["id"])
        gw.store.upsert_key({"provider": "openai", "label": "stand-in", "key": key, "priority": 1,
                             "base_url": f"http://127.0.0.1:{port}/openai/v1", "model": "gpt-4o-mini"})
    add("sk-visual-good-000000000001")
    yield add
    srv.shutdown()


def _vq(demo, **kw):
    from agentqa.agents.visual_qa import VisualQA
    p, _ = demo
    p.cfg.setdefault("llm", {})["enabled"] = True
    return VisualQA(p, ask_person=False, **kw)


def test_act_clicks_only_a_control_it_was_shown_and_verify_quotes_the_page(demo, portal, browser_page, ai):
    page = browser_page
    page.goto(portal + "/")
    vq = _vq(demo, url_of=lambda path: portal + path)
    assert vq.llm is not None
    res = vq.act(page, "Open the Help page")
    assert res["ok"] and res["by"] == "model" and res["actions"] == ["Clicked 'Help'"]
    assert page.url.endswith("/help")
    v = vq.verify(page, "The help page offers to contact the helpdesk")
    assert v["verdict"] == "pass" and "contact the helpdesk" in v["quote"]
    assert vq.quote_on_page(v["quote"], page.locator("body").inner_text())


def test_a_quote_that_is_not_on_the_page_is_never_a_pass(demo, portal, browser_page, ai):
    ai("sk-visual-liar-000000000002")
    page = browser_page
    page.goto(portal + "/help")
    v = _vq(demo).verify(page, "The certificate was issued")
    assert v["verdict"] == "unsure" and "not on the page" in v["why"]


def test_without_a_model_or_a_person_nothing_is_guessed(demo, portal, browser_page, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTQA_HOME", str(tmp_path / "empty-home"))
    page = browser_page
    page.goto(portal + "/")
    from agentqa.agents.visual_qa import VisualQA
    p, _ = demo
    vq = VisualQA(p, ask_person=False)
    assert vq.llm is None
    res = vq.act(page, "Open the Help page")
    assert not res["ok"] and not res["asked"] and "no AI model" in res["why"]
    assert vq.verify(page, "Help is shown")["verdict"] == "unsure"


def test_grounding_and_production_guards(demo, portal, browser_page, ai):
    page = browser_page
    page.goto(portal + "/")
    vq = _vq(demo)
    ob = vq.observe(page)
    assert any(e["text"] == "Help" for e in ob["elements"]) and "navigation" in ob["aria"]
    ok, why = vq._do(page, {"do": "click", "element": 999}, ob, None, False)
    assert not ok and "not on the page" in why
    box = next(e for e in ob["elements"] if e["tag"] == "input")
    ok, why = vq._do(page, {"do": "fill", "element": box["i"], "value": "income"}, ob, None, True)
    assert not ok and "production" in why
    ok, why = vq._do(page, {"do": "goto", "path": "https://elsewhere.example/"}, ob, None, False)
    assert not ok and "outside the test scope" in why
