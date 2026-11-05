"""M1.2 slice 2: the router knows local from cloud keys, honours a scope order (hybrid), picks a model per tier,
gives each key its own timeout, tries the next candidate model before cooling a key down, and reports token usage
for every family through `on_usage`."""
from __future__ import annotations

import threading
import time

import pytest
from cryptography.fernet import Fernet

from conftest import free_port

from agentqa.ai import catalog as C
from agentqa.ai import providers as P
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
    mock_ai.SEEN.clear()
    g = Gateway(AIStore())
    g.store.set_policy({"order": ["openai", "anthropic", "gemini", "ollama", "lmstudio"], "timeout_s": 5, "backoff_s": 0.05})
    g.base = f"http://127.0.0.1:{port}"
    yield g
    srv.shutdown()
    srv.server_close()


def add(g, provider, label, key, path, model="auto", prio=1, **kw):
    return g.store.upsert_key({"provider": provider, "label": label, "key": key, "base_url": g.base + path, "model": model,
                               "priority": prio, **kw})


def both(g):
    add(g, "ollama", "Ollama", "", "/ollama", "qwen3:4b")
    add(g, "openai", "OpenAI", "sk-cloud-good-0000000000000001", "/openai/v1", "gpt-4o-mini")


def test_scopes_filter_the_keys_and_keep_their_order(gw):
    both(gw)
    assert gw.complete_json("s", "u", scopes=("local",))["model"] == "qwen3:4b"
    assert gw.complete_json("s", "u", scopes=("cloud",))["model"] == "gpt-4o-mini"
    assert gw.complete_json("s", "u", scopes=("local", "cloud"))["model"] == "qwen3:4b"       # hybrid, cheap tier
    assert gw.complete_json("s", "u", scopes=("cloud", "local"))["model"] == "gpt-4o-mini"    # hybrid, strong tier
    assert gw.complete_json("s", "u")["model"] == "gpt-4o-mini"                                # the default is cloud only
    assert [k["label"] for k in gw.ordered(scopes=("local", "cloud"))] == ["Ollama", "OpenAI"]
    assert gw.ordered(scopes=("local",)) and not gw.ordered(scopes=("local",), need_vision=True)   # qwen3 cannot see


def test_an_ollama_on_another_machine_is_cloud_not_local(gw):
    gw.store.upsert_key({"provider": "ollama", "label": "Office box", "key": "", "model": "qwen3:4b",
                         "base_url": "http://10.0.0.5:11434"})
    assert not gw.ordered(scopes=("local",)) and gw.ordered(scopes=("cloud",))


def test_each_key_has_its_own_timeout_and_local_defaults_to_600s(gw):
    both(gw)
    pol = gw.store.policy()
    keys = {k["label"]: k for k in gw.store.keys()}
    assert gw.timeout_for(keys["Ollama"], pol) == 600 and gw.timeout_for(keys["OpenAI"], pol) == 5
    gw.store.upsert_key({"id": keys["OpenAI"]["id"], "timeout_s": 1, "model": "slow-model"})
    gw.store.set_policy({"attempts_per_key": 1})                    # one try: this PC adds ~1.5 s of client set-up per request
    started = time.time()
    assert gw.complete_json("s", "u", scopes=("cloud",)) is None
    assert time.time() - started < mock_ai.SLOW_S                   # the key's 1 s, not the policy's 5 s
    assert gw.store.events()[1]["outcome"] == "timeout"


def test_a_timeout_tries_the_next_candidate_model_before_cooling_the_key(gw):
    gw.store.set_policy({"attempts_per_key": 1})
    kid = add(gw, "openai", "OpenAI", "sk-cloud-good-0000000000000001", "/openai/v1", "slow-model", 1,
              fallback_model="gpt-4o-mini", timeout_s=1)
    out = gw.complete_json("s", "u")
    assert out["model"] == "gpt-4o-mini" and gw.last["model"] == "gpt-4o-mini"
    assert gw.store.state(kid)["state"] == "ok"                       # not cooling: the key still works
    outcomes = [e["outcome"] for e in reversed(gw.store.events())]
    assert outcomes == ["timeout", "ok"]


@pytest.mark.parametrize("tier,model", [("cheap", "claude-haiku-5-5"), ("balanced", "claude-sonnet-5-5"),
                                        ("strong", "claude-opus-5-5")])
def test_a_tier_chooses_the_model_for_an_auto_key(gw, tier, model):
    add(gw, "anthropic", "Claude", "sk-ant-good-0000000000000003", "/anthropic/v1", "auto")
    assert gw.complete_json("s", "u", tier=tier)["model"] == model


def test_a_pinned_model_ignores_the_tier(gw):
    add(gw, "anthropic", "Claude", "sk-ant-good-0000000000000003", "/anthropic/v1", "claude-haiku-5-5")
    assert gw.complete_json("s", "u", tier="strong")["model"] == "claude-haiku-5-5"


def test_on_usage_reports_tokens_for_all_four_families(gw):
    add(gw, "openai", "OpenAI", "sk-cloud-good-0000000000000001", "/openai/v1", "gpt-4o-mini", 1)
    add(gw, "anthropic", "Claude", "sk-ant-good-0000000000000003", "/anthropic/v1", "claude-sonnet-5-5", 1)
    add(gw, "gemini", "Gemini", "AIzaGood00000000000000000000001", "/gemini/v1beta", "gemini-flash-latest", 1)
    add(gw, "ollama", "Ollama", "", "/ollama", "qwen3:4b", 1)
    seen: list[dict] = []
    for provider in ("openai", "anthropic", "gemini", "ollama"):
        gw.store.set_policy({"order": [provider], "provider_fallback": False})
        scopes = ("local",) if provider == "ollama" else ("cloud",)
        assert gw.complete_json("s", "u", task="t", tier="cheap", scopes=scopes, on_usage=seen.append)
    assert [u["provider"] for u in seen] == ["openai", "anthropic", "gemini", "ollama"]
    for u in seen:
        assert u["input_tokens"] == 1 and u["ms"] >= 0 and u["tier"] == "cheap" and u["task"] == "t" and u["usage_known"]
    assert [u["output_tokens"] for u in seen] == [1, 1, 2, 1]                  # Gemini: thinking tokens are billed output
    assert [u["scope"] for u in seen] == ["cloud", "cloud", "cloud", "local"]
    assert seen[3]["model"] == "qwen3:4b" and seen[1]["label"] == "Claude"


def test_on_switch_reports_each_move_to_another_provider_with_its_reason_and_nothing_secret(gw):
    # C4 (M1.3 Phase C): the Live View learns of a switch; a move between two keys of one provider is not reported
    add(gw, "openai", "OpenAI Primary", "sk-one-ratelimit-000000000001", "/openai/v1", "gpt-4o-mini", 1)
    add(gw, "openai", "OpenAI Backup", "sk-two-invalid-0000000000002", "/openai/v1", "gpt-4o-mini", 2)
    add(gw, "anthropic", "Claude personal", "sk-ant-nocredit-0000000000003", "/anthropic/v1", "claude-opus-5-5", 1)
    add(gw, "gemini", "Gemini", "AIzaGood00000000000000000000004", "/gemini/v1beta", "gemini-flash-lite-latest", 1)
    seen: list[dict] = []
    assert gw.complete_json("SYS-MARK", "USER-MARK", task="req_writer", on_switch=seen.append)["served_by"] == "000004"
    assert seen == [
        {"from_provider": "openai", "to_provider": "anthropic", "kind": "invalid_key", "reason": "Key rejected",
         "task": "req_writer"},
        {"from_provider": "anthropic", "to_provider": "gemini", "kind": "billing", "reason": "Billing or credit exhausted",
         "task": "req_writer"},
    ]
    assert [e["outcome"] for e in gw.store.events()].count("switched") == 3     # the audit log keeps all three
    seen.clear()
    assert gw.complete_json("s", "u", on_switch=seen.append)["served_by"] == "000004"
    assert seen == []                                    # every key before Gemini is dead or cooling: nothing to switch


def test_a_broken_switch_callback_never_loses_the_answer(gw):
    add(gw, "anthropic", "Claude", "sk-ant-nocredit-0000000000003", "/anthropic/v1", "claude-opus-5-5", 1)
    add(gw, "gemini", "Gemini", "AIzaGood00000000000000000000004", "/gemini/v1beta", "gemini-flash-lite-latest", 1)

    called: list[dict] = []

    def boom(info):
        called.append(info)
        raise RuntimeError("the live line is broken")
    assert gw.complete_json("s", "u", on_switch=boom)["served_by"] == "000004"
    assert len(called) == 1


def test_a_broken_usage_callback_never_loses_the_answer(gw):
    add(gw, "openai", "OpenAI", "sk-cloud-good-0000000000000001", "/openai/v1", "gpt-4o-mini")

    def boom(u):
        raise RuntimeError("the cost record is broken")
    assert gw.complete_json("s", "u", on_usage=boom)["ok"] is True


def test_redaction_applies_to_cloud_keys_only(gw, monkeypatch):
    both(gw)
    sent: list[tuple[str, str]] = []

    class Spy(P.Adapter):
        def models(self):
            return ["m"]

        def chat(self, model, system, user, max_tokens, image):
            sent.append((self.k["provider"], user))
            return '{"ok": true}'
    monkeypatch.setattr(P, "adapter", lambda key, timeout=60: Spy(key, timeout))
    text = "Citizen 9123456780 with qa@example.com and Aadhaar 1234 5678 9012"
    gw.complete_json("s", text, scopes=("cloud",))
    gw.complete_json("s", text, scopes=("local",))
    cloud = next(u for p, u in sent if p == "openai")
    local = next(u for p, u in sent if p == "ollama")
    assert "9123456780" not in cloud and "qa@example.com" not in cloud and "1234 5678 9012" not in cloud
    assert local == text                                                 # nothing leaves the PC: nothing to mask


def test_an_image_is_dropped_for_a_key_that_cannot_see_and_kept_for_one_that_can(gw):
    both(gw)
    gw.complete_json("s", "u", scopes=("local",), image=b"\xff\xd8jpeg")
    gw.complete_json("s", "u", scopes=("cloud",), image=b"\xff\xd8jpeg", cloud_image=True)
    assert mock_ai.SEEN[""]["image"] is False                            # Ollama (keyless): no image
    assert mock_ai.SEEN["sk-cloud-good-0000000000000001"]["image"] is True


def test_last_is_per_thread(gw):
    both(gw)
    gw.complete_json("s", "u", scopes=("cloud",))
    inside: dict = {}

    def worker():
        gw.complete_json("s", "u", scopes=("local",))
        inside.update(gw.last)
    t = threading.Thread(target=worker)
    t.start()
    t.join(30)
    assert inside["model"] == "qwen3:4b" and gw.last["model"] == "gpt-4o-mini"


# ---- review fixes (fresh-context reviews, 3 Nov 2026) ------------------------------------------------------

def test_an_image_never_reaches_a_cloud_key_without_consent_even_in_hybrid(gw):
    add(gw, "openai", "OpenAI", "sk-cloud-good-0000000000000001", "/openai/v1", "gpt-4o-mini")
    add(gw, "ollama", "Llava", "", "/ollama", "llava:7b")                                 # a local model that can see
    out = gw.complete_json("s", "u", scopes=("cloud", "local"), image=b"\xff\xd8jpeg", cloud_image=False)
    assert out["model"] == "gpt-4o-mini" and mock_ai.SEEN["sk-cloud-good-0000000000000001"]["image"] is False
    out = gw.complete_json("s", "u", scopes=("cloud", "local"), image=b"\xff\xd8jpeg", cloud_image=False, need_vision=True)
    assert out["model"] == "llava:7b" and mock_ai.SEEN[""]["image"] is True            # cloud keys skipped entirely
    out = gw.complete_json("s", "u", scopes=("cloud",), image=b"\xff\xd8jpeg", cloud_image=True)
    assert mock_ai.SEEN["sk-cloud-good-0000000000000001"]["image"] is True


def test_empty_scopes_fail_closed(gw):
    both(gw)
    assert gw.complete_json("s", "u", scopes=()) is None and not gw.ordered(scopes=())
    assert mock_ai.CALLS == {}


def test_a_dead_tier_model_does_not_disable_the_key_for_other_tiers(gw, monkeypatch):
    monkeypatch.setitem(C.TIERS, "openai", {"strong": ["retired-model"], "cheap": ["gpt-4o-mini"]})
    monkeypatch.setattr(mock_ai, "MODELS", mock_ai.MODELS + ["retired-model"])
    gw.store.set_policy({"attempts_per_key": 1})
    kid = add(gw, "openai", "OpenAI", "sk-cloud-good-0000000000000001", "/openai/v1", "auto")
    assert gw.complete_json("s", "u", tier="strong") is None
    assert gw.store.state(kid)["state"] != "model"                               # the key still works for other tiers
    assert gw.complete_json("s", "u", tier="cheap")["model"] == "gpt-4o-mini"
    before = mock_ai.CALLS["sk-cloud-good-0000000000000001"]
    assert gw.complete_json("s", "u", tier="strong") is None and mock_ai.CALLS["sk-cloud-good-0000000000000001"] == before  # not retried


def test_usage_is_reported_for_billed_but_unusable_answers_and_flags_unknown_usage(gw):
    gw.store.set_policy({"attempts_per_key": 1})
    add(gw, "openai", "Garbage", "sk-cloud-garbage-00000000000001", "/openai/v1", "gpt-4o-mini", 1)
    seen: list[dict] = []
    assert gw.complete_json("s", "u", on_usage=seen.append) is None
    assert len(seen) == 1 and seen[0]["ok"] is False and seen[0]["input_tokens"] == 1 and seen[0]["usage_known"]
    for k in gw.store.keys():
        gw.store.delete_key(k["id"])
    add(gw, "openai", "Silent", "sk-cloud-nousage-good-000000001", "/openai/v1", "gpt-4o-mini", 1)
    seen.clear()
    assert gw.complete_json("system text", "user text", max_tokens=321, on_usage=seen.append)["ok"]
    u = seen[0]
    assert u["ok"] and not u["usage_known"] and u["input_tokens"] == 0 and u["max_tokens"] == 321 and u["approx_input_tokens"] > 0
