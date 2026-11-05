"""Requirement 1: several providers and keys, failover by kind of failure, audit log, keys never exposed."""
from __future__ import annotations

import time

import pytest
from cryptography.fernet import Fernet

from conftest import free_port

from demo import mock_ai


@pytest.fixture
def gw(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTQA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AGENTQA_VAULT_KEY", Fernet.generate_key().decode())
    from agentqa.ai.router import Gateway
    from agentqa.ai.store import AIStore
    port = free_port()
    srv = mock_ai.serve(port)
    mock_ai.CALLS.clear()
    g = Gateway(AIStore())
    g.store.set_policy({"order": ["openai", "anthropic", "gemini"], "timeout_s": 2, "backoff_s": 0.05})
    g.base = f"http://127.0.0.1:{port}"
    yield g
    srv.shutdown()


def add(g, provider, label, key, path, model="auto", prio=1, **kw):
    return g.store.upsert_key({"provider": provider, "label": label, "key": key, "base_url": g.base + path, "model": model,
                               "priority": prio, **kw})


def test_an_answer_records_its_token_usage_for_the_cost_record(gw):
    add(gw, "anthropic", "Claude", "sk-ant-good-0000000000000003", "/anthropic/v1", "claude-sonnet-5-5", 1)
    assert gw.complete_json("s", "u", task="t")["served_by"] == "000003"
    ok = next(e for e in gw.store.events(10) if e["outcome"] == "ok")
    assert "1 in / 1 out tokens" in ok["detail"]          # the stand-in reports usage {input: 1, output: 1}


def test_failover_walks_the_keys_and_never_retries_a_rejected_key(gw):
    p1 = add(gw, "openai", "OpenAI Primary", "sk-one-ratelimit-000000000001", "/openai/v1", "gpt-4o-mini", 1)
    p2 = add(gw, "openai", "OpenAI Secondary", "sk-two-invalid-0000000000002", "/openai/v1", "gpt-4o-mini", 2)
    p3 = add(gw, "openai", "OpenAI Backup", "sk-three-good-000000000000003", "/openai/v1", "gpt-4o-mini", 3)
    out = gw.complete_json("s", "u", task="t")
    assert out["served_by"] == "000003" and gw.last["label"] == "OpenAI Backup"
    states = {s["key_id"]: s for s in gw.store.states()}
    assert states[p1]["state"] == "cooling" and states[p1]["cooldown_until"] > time.time() + 20   # Retry-After: 30
    assert states[p2]["state"] == "invalid_key"
    for _ in range(3):
        assert gw.complete_json("s", "u")["served_by"] == "000003"
    assert mock_ai.CALLS["sk-two-invalid-0000000000002"] == 1          # a rejected key is tried once, not again
    assert mock_ai.CALLS["sk-one-ratelimit-000000000001"] == 1         # a cooling key waits out its cool-down
    outcomes = [e["outcome"] for e in reversed(gw.store.events())]
    assert outcomes[:5] == ["rate_limit", "switched", "invalid_key", "switched", "ok"]
    assert gw.store.state(p3)["state"] == "ok"


def test_provider_fallback_model_fallback_and_billing(gw):
    add(gw, "openai", "OpenAI billing", "sk-x-billing-000000000000001", "/openai/v1", "gpt-4o-mini", 1)
    add(gw, "openai", "OpenAI down", "sk-x-down-0000000000000000002", "/openai/v1", "gpt-4o-mini", 2)
    ant = add(gw, "anthropic", "Claude", "sk-ant-good-0000000000000003", "/anthropic/v1", "retired-model", 1,
              fallback_model="claude-sonnet-5-5")
    out = gw.complete_json("s", "u")
    assert out["model"] == "claude-sonnet-5-5" and gw.last["provider"] == "anthropic"
    st = {s["key_id"]: s for s in gw.store.states()}
    billing = next(k for k in gw.store.keys() if k["label"] == "OpenAI billing")
    assert st[billing["id"]]["state"] == "billing"                         # insufficient_quota is billing, not a rate limit
    assert mock_ai.CALLS["sk-x-down-0000000000000000002"] == 2            # outages: tried attempts_per_key times
    assert st[ant]["dead_model"] == ["retired-model"]                       # M1.2: one list per key, a model per tier
    gw.complete_json("s", "u")
    assert mock_ai.CALLS["sk-ant-good-0000000000000003"] == 3             # the dead model is not asked again


@pytest.mark.parametrize("provider,key,path,model", [
    ("anthropic", "sk-ant-nocredit-0000000000001", "/anthropic/v1", "claude-opus-5-5"),   # 4 Nov 2026: asked 27 times
    ("openai", "sk-oa-hardlimit-000000000001", "/openai/v1", "gpt-4o-mini"),              # through the shared _send
])
def test_a_key_that_cannot_pay_is_billing_after_one_call_and_never_asked_again(gw, provider, key, path, model):
    dead = add(gw, provider, "No credit", key, path, model, 1)
    add(gw, "gemini", "Gemini", "AIzaGood00000000000000000000002", "/gemini/v1beta", "gemini-flash-lite-latest", 1)
    for _ in range(4):
        assert gw.complete_json("s", "u")["served_by"] == "000002"
    assert gw.store.state(dead)["state"] == "billing"
    assert mock_ai.CALLS[key] == 1
    assert [e["outcome"] for e in reversed(gw.store.events())] == ["billing", "switched", "ok", "ok", "ok", "ok"]


def test_test_connection_says_billing_and_an_edit_gives_the_key_a_fresh_chance(gw):
    ant = add(gw, "anthropic", "Claude", "sk-ant-nocredit-0000000000001", "/anthropic/v1", "claude-opus-5-5", 1)
    res = gw.test(ant)
    assert not res["ok"] and res["kind"] == "billing" and gw.store.state(ant)["state"] == "billing"
    assert not gw.available()
    gw.store.upsert_key({"id": ant, "key": "sk-ant-good-0000000000000003"})       # credit added, key edited
    assert gw.complete_json("s", "u")["served_by"] == "000003"


def test_quota_timeouts_and_all_failed(gw):
    gw.store.set_policy({"order": ["gemini"], "attempts_per_key": 1, "timeout_s": 1})
    add(gw, "gemini", "Gemini quota", "AIzaQuota000000000000000000001", "/gemini/v1beta", "gemini-2.5-flash", 1)
    add(gw, "gemini", "Gemini slow", "AIzaSlow0000000000000000000002", "/gemini/v1beta", "gemini-2.5-flash", 2)
    assert gw.complete_json("s", "u") is None
    outcomes = [e["outcome"] for e in gw.store.events()]
    assert "quota" in outcomes and "timeout" in outcomes
    assert gw.store.events()[0]["outcome"] == "all_failed"
    assert not gw.available()                                             # both cooling down now


def test_keys_are_encrypted_scrubbed_from_logs_and_masked_for_the_dashboard(gw, tmp_path):
    kid = add(gw, "openai", "Bad", "sk-secret-invalid-ABCDEF123456", "/openai/v1", "gpt-4o-mini")
    gw.complete_json("s", "u")
    res = gw.test(kid)
    assert not res["ok"] and res["kind"] == "invalid_key"
    raw = (gw.store.vault.read_bytes() + gw.store.db_path.read_bytes())
    assert b"sk-secret-invalid-ABCDEF123456" not in raw
    assert "sk-secret-invalid-ABCDEF123456" not in gw.store.scrub("echo sk-secret-invalid-ABCDEF123456 back")
    pub = gw.store.public_keys()[0]
    assert "key" not in pub and pub["masked"] == "sk-s…3456"


def test_edit_gives_a_dead_key_a_fresh_chance(gw):
    kid = add(gw, "openai", "K", "sk-k-invalid-000000000000001", "/openai/v1", "gpt-4o-mini")
    gw.complete_json("s", "u")
    assert gw.store.state(kid)["state"] == "invalid_key"
    gw.store.upsert_key({"id": kid, "key": "sk-k-good-00000000000000000002"})
    assert gw.complete_json("s", "u")["served_by"] == "000002"


def test_test_connection_lists_models_and_picks_one(gw):
    kid = add(gw, "gemini", "G", "AIzaGood00000000000000000000001", "/gemini/v1beta", "auto")
    res = gw.test(kid)
    assert res["ok"] and res["model"] == "gemini-flash-latest" and "gemini-2.5-pro" in res["models"]   # M1.2: -latest alias first
    assert gw.store.state(kid)["state"] == "ok"
