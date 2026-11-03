"""M1.2 slice 4: `model_for(project, agent)` — the one door every agent uses. None (with a reason) when the project's
mode, consent, budget or keys say no; otherwise a duck-typed client (available, chat_json, complete_json, model,
enabled, image_allowed) that routes by scope and tier, withholds images without consent, redacts cloud text,
records usage in the project store with the pipeline id, and announces its model once."""
from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet

from conftest import free_port

from agentqa import live
from agentqa.ai import client as AC
from agentqa.ai import providers as P
from agentqa.ai import usage as U
from agentqa.store import Store
from demo import mock_ai

CLOUD_KEY = "sk-client-good-000000000000001"


@pytest.fixture
def ai(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AGENTQA_VAULT_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("AGENTQA_PIPELINE_ID", raising=False)
    port = free_port()
    srv = mock_ai.serve(port)
    mock_ai.CALLS.clear()
    mock_ai.SEEN.clear()
    AC._ANNOUNCED.clear()
    from agentqa.ai import gateway
    gw = gateway()
    gw.store.set_policy({"order": ["openai", "ollama"], "timeout_s": 5, "backoff_s": 0.05})
    gw.store.upsert_key({"provider": "openai", "label": "cloud", "key": CLOUD_KEY, "priority": 1,
                         "base_url": f"http://127.0.0.1:{port}/openai/v1", "model": "gpt-4o-mini"})
    gw.store.upsert_key({"provider": "ollama", "label": "local", "key": "", "priority": 1,
                         "base_url": f"http://127.0.0.1:{port}/ollama", "model": "qwen3:4b"})
    yield gw
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def events(tmp_path, monkeypatch):
    folder = tmp_path / "live"
    monkeypatch.setenv("AGENTQA_LIVE_DIR", str(folder))
    monkeypatch.setattr(live, "_LIVE", None)
    yield lambda: [json.loads(ln) for ln in (folder / "events-main.jsonl").read_text(encoding="utf-8").splitlines()] \
        if (folder / "events-main.jsonl").exists() else []
    monkeypatch.setattr(live, "_LIVE", None)


def configure(demo, mode: str, **ai) -> None:
    p, _ = demo
    consent = {"send_text": ai.pop("send_text", mode != "local"), "send_screenshots": ai.pop("send_screenshots", False)}
    p.cfg["ai"] = {"mode": mode, "consent": consent, **ai}


def test_no_ai_mode_returns_none_without_touching_the_key_store(demo, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_HOME", str(tmp_path / "untouched"))
    configure(demo, "none")
    assert AC.model_for(demo[0], "casegen") is None
    assert not (tmp_path / "untouched").exists()


def test_the_client_speaks_the_old_interface_and_the_gateway_one(demo, ai):
    configure(demo, "cloud")
    llm = AC.model_for(demo[0], "casegen")
    assert llm is not None and llm.enabled and llm.reason is None and llm.available() and not llm.image_allowed
    out = llm.chat_json("Reply with JSON only.", 'Return {"ok": true}', 50)
    assert out["ok"] is True and out["model"] == "gpt-4o-mini" and llm.model.endswith("gpt-4o-mini")
    out = llm.complete_json("s", "u", task="req_chat", max_tokens=200)
    assert out["ok"] is True
    assert "cloud" in llm.model


def test_local_mode_uses_the_local_key_and_cloud_mode_never_does(demo, ai):
    configure(demo, "local")
    assert AC.model_for(demo[0], "req_writer").chat_json("s", "u")["model"] == "qwen3:4b"
    configure(demo, "cloud")
    assert AC.model_for(demo[0], "req_writer").chat_json("s", "u")["model"] == "gpt-4o-mini"
    assert mock_ai.CALLS[""] == 1 and mock_ai.CALLS[CLOUD_KEY] == 1


def test_an_image_is_withheld_without_consent_and_sent_with_it(demo, ai):
    configure(demo, "cloud", send_screenshots=False)
    AC.model_for(demo[0], "visual_qa").chat_json("s", "u", 50, image_jpeg=b"\xff\xd8jpeg")
    assert mock_ai.SEEN[CLOUD_KEY]["image"] is False
    configure(demo, "cloud", send_screenshots=True)
    llm = AC.model_for(demo[0], "visual_qa")
    assert llm.image_allowed
    llm.chat_json("s", "u", 50, image_jpeg=b"\xff\xd8jpeg")
    assert mock_ai.SEEN[CLOUD_KEY]["image"] is True


def test_cloud_text_is_redacted(demo, ai, monkeypatch):
    sent: list[str] = []

    class Spy(P.Adapter):
        def models(self):
            return ["m"]

        def chat(self, model, system, user, max_tokens, image):
            sent.append(user)
            return '{"ok": true}'
    monkeypatch.setattr(P, "adapter", lambda key, timeout=60: Spy(key, timeout))
    configure(demo, "cloud")
    AC.model_for(demo[0], "srs").chat_json("s", "Citizen 9123456780, qa@example.com, Aadhaar 1234 5678 9012")
    assert sent and "9123456780" not in sent[0] and "qa@example.com" not in sent[0] and "1234 5678 9012" not in sent[0]


def test_usage_is_recorded_in_the_project_store_with_the_pipeline_id(demo, ai, monkeypatch):
    monkeypatch.setenv("AGENTQA_PIPELINE_ID", "P-42")
    configure(demo, "cloud")
    AC.model_for(demo[0], "casegen").chat_json("s", "u")
    rows = Store(demo[0].db_path).all("SELECT * FROM ai_usage")
    assert len(rows) == 1
    r = rows[0]
    assert r["pipeline"] == "P-42" and r["agent"] == "casegen" and r["tier"] == "balanced" and r["scope"] == "cloud"
    assert r["provider"] == "openai" and r["model"] == "gpt-4o-mini" and r["input_tokens"] == 1 and r["output_tokens"] == 1
    assert r["cost_usd"] == pytest.approx((0.15 + 0.60) / 1_000_000) and not r["estimated"]


def test_the_model_event_is_announced_once_per_agent(demo, ai, events):
    configure(demo, "local")
    AC.model_for(demo[0], "casegen")
    AC.model_for(demo[0], "casegen")
    AC.model_for(demo[0], "triage")
    ev = [e for e in events() if e["agent"] == "ai" and e["kind"] == "model"]
    assert [e["agent_key"] for e in ev] == ["casegen", "triage"]
    assert "qwen3:4b" in ev[0]["title"] and ev[0]["tier"] == "balanced" and ev[0]["mode"] == "local"


def test_a_reason_is_announced_when_there_is_no_model(demo, ai, events):
    configure(demo, "cloud", send_text=False)
    assert AC.model_for(demo[0], "casegen") is None
    ev = [e for e in events() if e["kind"] == "model"]
    assert len(ev) == 1 and "not allowed text" in ev[0]["reason"]


NO_CREDIT_KEY = "sk-ant-nocredit-000000000001"


def add_out_of_credit_key(gw, *, only_cloud_key: bool) -> None:
    """An Anthropic key whose credit is used up (the stand-in's `nocredit`), asked before the fixture's OpenAI key,
    or instead of it."""
    cloud = next(k for k in gw.store.keys() if k["provider"] == "openai")
    if only_cloud_key:
        gw.store.delete_key(cloud["id"])
    gw.store.set_policy({"order": ["anthropic", "openai", "ollama"]})
    gw.store.upsert_key({"provider": "anthropic", "label": "claude-label-5e2", "key": NO_CREDIT_KEY, "priority": 1,
                         "base_url": cloud["base_url"].replace("/openai/v1", "/anthropic/v1"), "model": "claude-opus-5-5"})


def test_a_cloud_key_out_of_credit_is_not_planned_for_the_next_agents(demo, ai, events):
    # C5: the empty key answers once; the next agent says why there is no model instead of asking it again
    configure(demo, "cloud")
    add_out_of_credit_key(ai, only_cloud_key=True)
    assert AC.model_for(demo[0], "casegen").chat_json("s", "u") is None
    assert AC.model_for(demo[0], "triage") is None
    assert mock_ai.CALLS[NO_CREDIT_KEY] == 1
    [triage] = [e for e in events() if e["kind"] == "model" and e["agent_key"] == "triage"]
    assert triage["reason"] == AC.modes.NO_CLOUD


def spend(store: Store, usd: float) -> None:
    U.record(store, {"provider": "openai", "model": "unit", "scope": "cloud", "input_tokens": int(usd * 1_000_000),
                     "output_tokens": 0, "ms": 1}, agent="casegen", pipeline="old", prices={"openai": {"unit": [1, 1]}})


def test_at_the_cap_no_request_reaches_the_provider_and_the_agent_gets_none(demo, ai, events):
    configure(demo, "cloud", budget={"monthly_usd": 0.5, "alert_at_pct": 80})
    spend(Store(demo[0].db_path), 0.6)
    assert AC.model_for(demo[0], "casegen") is None
    assert AC.model_for(demo[0], "triage") is None
    assert CLOUD_KEY not in mock_ai.CALLS
    cost = [e for e in events() if e["kind"] == "cost"]
    assert len(cost) == 1 and cost[0]["state"] == "capped"                 # two capped look-ups, one alert


def test_the_cap_is_checked_before_every_cloud_call_not_only_at_start(demo, ai):
    configure(demo, "cloud", budget={"monthly_usd": 0.5, "alert_at_pct": 80})
    llm = AC.model_for(demo[0], "casegen")
    assert llm.chat_json("s", "u")["ok"]
    spend(Store(demo[0].db_path), 0.6)                                      # another worker spent it meanwhile
    assert llm.chat_json("s", "u") is None and mock_ai.CALLS[CLOUD_KEY] == 1
    assert "budget" in llm.reason


def test_hybrid_keeps_answering_locally_at_the_cap(demo, ai):
    configure(demo, "hybrid", budget={"monthly_usd": 0.5, "alert_at_pct": 80})
    spend(Store(demo[0].db_path), 0.6)
    llm = AC.model_for(demo[0], "req_writer")                               # strong: cloud first in hybrid
    assert llm is not None and llm.chat_json("s", "u")["model"] == "qwen3:4b"
    assert CLOUD_KEY not in mock_ai.CALLS


def test_the_effective_table_names_the_model_or_the_reason(demo, ai):
    configure(demo, "hybrid", assignments={"triage": "off"})
    rows = {r["agent"]: r for r in AC.effective(demo[0])}
    assert rows["triage"]["reason"] and rows["triage"]["model"] is None
    assert rows["req_writer"]["provider"] == "openai" and rows["req_writer"]["model"] == "gpt-4o-mini"
    assert rows["login"]["provider"] == "ollama" and rows["login"]["model"] == "qwen3:4b"
    assert rows["documents"]["reason"] and "image" in rows["documents"]["reason"]
    assert all(set(r) >= {"agent", "label", "tier", "scopes", "provider", "model", "reason"} for r in rows.values())


# ---- review fixes (fresh-context reviews, 3 Nov 2026) ------------------------------------------------------

def test_the_client_closes_its_store_and_works_as_a_context_manager(demo, ai):
    import sqlite3
    configure(demo, "local")
    with AC.model_for(demo[0], "casegen") as llm:
        assert llm.chat_json("s", "u")["model"] == "qwen3:4b"
    with pytest.raises(sqlite3.ProgrammingError):
        llm.store.conn.execute("SELECT 1")
    other = AC.model_for(demo[0], "triage")
    other.close()
    other.close()                                                           # closing twice is fine


def test_model_names_this_clients_own_last_answer(demo, ai):
    configure(demo, "local")
    a = AC.model_for(demo[0], "casegen")
    b = AC.model_for(demo[0], "req_writer")
    a.chat_json("s", "u")
    assert "qwen3:4b" in a.model and "qwen3:4b" not in b.model and "tier" in b.model


def test_ocr_goes_through_the_documents_client_only_with_consent(demo, ai, monkeypatch):
    from agentqa import documents
    monkeypatch.setattr(documents, "_tesseract", lambda: None)
    assert documents.ocr(b"\xff\xd8jpeg", None) == (None, documents.ocr(b"", None)[1])

    class FakeAi:
        calls: list[dict] = []

        def complete_json(self, system, user, **kw):
            self.calls.append(kw)
            return {"text": "Section 1 | Fees"}
    text, how = documents.ocr(b"\xff\xd8jpeg", FakeAi())
    assert text == "Section 1 | Fees" and how == "AI vision model" and FakeAi.calls[0]["image"] == b"\xff\xd8jpeg"
    configure(demo, "cloud", send_screenshots=False)
    assert AC.model_for(demo[0], "documents") is None                     # no consent: OCR never gets a client


# ---- M1.3: one `cost` line per billed call, for the Live View's cards -------------------------------------------

COST_FIELDS = {"t", "seq", "w", "agent", "kind", "title", "agent_key", "tier", "scope", "provider", "model",
               "input_tokens", "output_tokens", "cost_usd", "estimated", "ms", "ok"}


def test_every_billed_call_writes_one_cost_line_with_figures_but_no_text_or_key(demo, ai, events):
    configure(demo, "cloud")
    llm = AC.model_for(demo[0], "casegen")
    llm.chat_json("SYSTEM-MARKER-7f3", "USER-MARKER-9c1", 50)
    costs = [e for e in events() if e["kind"] == "cost"]
    assert len(costs) == 1
    c = costs[0]
    assert set(c) <= COST_FIELDS and "state" not in c                   # never the prompt, the answer or the key
    assert c["agent"] == "ai" and c["agent_key"] == "casegen" and c["tier"] == "balanced" and c["scope"] == "cloud"
    assert c["provider"] == "openai" and c["model"] == "gpt-4o-mini" and c["ok"] is True and c["estimated"] is False
    assert c["input_tokens"] == 1 and c["output_tokens"] == 1
    assert c["cost_usd"] == pytest.approx((0.15 + 0.60) / 1_000_000)
    assert c["title"].startswith(f"{AC.modes.AGENTS['casegen']['label']}: gpt-4o-mini")
    blob = json.dumps(events())
    assert "MARKER" not in blob and CLOUD_KEY not in blob


def test_a_local_call_is_a_free_cost_line(demo, ai, events):
    configure(demo, "local")
    AC.model_for(demo[0], "casegen").chat_json("s", "u")
    [c] = [e for e in events() if e["kind"] == "cost"]
    assert c["scope"] == "local" and c["cost_usd"] == 0 and c["model"] == "qwen3:4b"


# ---- C4 (M1.3 Phase C): one `switched` line when a call moves to another provider -----------------------------

SWITCH_FIELDS = {"t", "seq", "w", "agent", "kind", "title", "agent_key", "tier", "from_provider", "to_provider",
                 "failure"}


def test_a_switch_to_another_provider_writes_one_live_line_without_key_label_or_prompt(demo, ai, events):
    configure(demo, "cloud")
    add_out_of_credit_key(ai, only_cloud_key=False)
    llm = AC.model_for(demo[0], "casegen")
    assert llm.chat_json("SYSTEM-MARKER-7f3", "USER-MARKER-9c1")["ok"] is True
    assert llm.chat_json("s", "u")["ok"] is True                   # the empty key is dead now: no second switch
    [s] = [e for e in events() if e["kind"] == "switched"]
    assert set(s) <= SWITCH_FIELDS
    assert (s["agent"], s["agent_key"], s["tier"]) == ("ai", "casegen", "balanced")
    assert (s["from_provider"], s["to_provider"], s["failure"]) == ("anthropic", "openai", "billing")
    label = AC.modes.AGENTS["casegen"]["label"]
    assert s["title"] == f"{label}: switched from Anthropic Claude to OpenAI (Billing or credit exhausted)"
    blob = json.dumps(events())
    assert not any(secret in blob for secret in ("MARKER", "nocredit", "claude-label-5e2", CLOUD_KEY))


def test_the_answer_is_kept_when_the_switch_line_cannot_be_written(demo, ai, monkeypatch):
    configure(demo, "cloud")
    add_out_of_credit_key(ai, only_cloud_key=False)
    llm = AC.model_for(demo[0], "casegen")
    tried: list[str] = []

    def broken(agent, kind, title, **fields):
        if kind == "switched":
            tried.append(title)
            raise RuntimeError("disk full")
    monkeypatch.setattr(AC.live, "emit", broken)
    assert llm.chat_json("s", "u")["ok"] is True
    assert len(tried) == 1


def test_the_switch_line_still_reads_for_an_unknown_agent_or_provider(events):
    AC._emit_switch("made-up-agent", "cheap", {"to_provider": "acme-ai", "kind": "timeout"})
    [s] = events()
    assert s["title"] == "made-up-agent: switched from ? to acme-ai (timeout)"
    assert (s["from_provider"], s["to_provider"], s["failure"]) == ("?", "acme-ai", "timeout")


def test_the_usage_row_is_kept_and_the_answer_returned_when_the_live_line_cannot_be_written(demo, ai, monkeypatch):
    configure(demo, "cloud")
    llm = AC.model_for(demo[0], "casegen")

    def broken(agent, kind, title, **fields):
        if kind == "cost":
            raise RuntimeError("disk full")
    monkeypatch.setattr(AC.live, "emit", broken)
    assert llm.chat_json("s", "u")["ok"] is True
    assert len(Store(demo[0].db_path).all("SELECT * FROM ai_usage")) == 1
