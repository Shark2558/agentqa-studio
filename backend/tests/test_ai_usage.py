"""M1.2 slice 3: the ai_usage table in the project store — cost from a date-stamped price table, local = $0, unknown
cloud prices estimated and flagged, never a word of any prompt, and the month / per-agent / per-run queries."""
from __future__ import annotations

import pytest

from agentqa.ai import usage as U
from agentqa.store import Store

MARKER = "PLANTED-PROMPT-TEXT-9f3a"


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "agentqa.db")


def info(**over) -> dict:
    base = {"provider": "anthropic", "label": "Claude", "key_id": "k1", "model": "claude-sonnet-5-5", "scope": "cloud",
            "tier": "balanced", "task": "casegen", "ms": 120, "input_tokens": 1_000_000, "output_tokens": 100_000,
            "system": MARKER, "user": MARKER, "answer": MARKER}
    return {**base, **over}


def test_the_price_table_is_date_stamped_and_has_the_tier_models():
    assert U.PRICES_DATED == "2026-11-03"
    for provider, model in (("anthropic", "claude-opus-5-5"), ("anthropic", "claude-sonnet-5-5"), ("anthropic", "claude-haiku-5-5"),
                            ("gemini", "gemini-flash-lite-latest"), ("gemini", "gemini-flash-latest"), ("gemini", "gemini-pro-latest"),
                            ("openai", "gpt-4o-mini")):
        inp, out, estimated = U.price_for(provider, model)
        assert inp > 0 and out > inp and not estimated, (provider, model)


def test_cost_is_tokens_times_the_price_per_million():
    cost, estimated = U.cost_usd("anthropic", "claude-sonnet-5-5", 1_000_000, 100_000)
    assert cost == pytest.approx(2.0 + 1.0) and not estimated
    cost, estimated = U.cost_usd("anthropic", "claude-haiku-5-5", 10_000, 1_000)
    assert cost == pytest.approx(0.001 + 0.0005) and not estimated


def test_local_models_cost_nothing():
    assert U.cost_usd("ollama", "qwen3:4b", 5_000_000, 5_000_000, scope="local") == (0.0, False)
    assert U.price_for("lmstudio", "anything", scope="local") == (0.0, 0.0, False)


def test_an_unknown_cloud_model_is_charged_at_the_providers_highest_price_and_flagged():
    inp, out, estimated = U.price_for("anthropic", "claude-unknown-9")
    assert (inp, out) == U.price_for("anthropic", "claude-opus-5-5")[:2] and estimated
    inp, out, estimated = U.price_for("mistral", "mistral-small-latest")          # provider without a table
    assert estimated and out == max(o for p in U.DEFAULT_PRICES.values() for _, o in p.values())


def test_policy_prices_override_the_defaults():
    prices = {"openai": {"gpt-4o-mini": [1.0, 2.0]}}
    assert U.price_for("openai", "gpt-4o-mini", prices) == (1.0, 2.0, False)
    assert U.price_for("openai", "gpt-4o", prices)[:2] == (2.5, 10.0)          # the rest of the table survives
    assert U.cost_usd("openai", "gpt-4o-mini", 1_000_000, 1_000_000, prices) == (3.0, False)


def test_record_keeps_the_numbers_and_never_the_prompt(store):
    row = U.record(store, info(), agent="casegen", pipeline="P-1")
    assert row["cost_usd"] == pytest.approx(3.0) and row["estimated"] == 0 and row["agent"] == "casegen"
    cols = store.all("SELECT * FROM ai_usage")
    assert len(cols) == 1
    blob = " ".join(str(v) for v in cols[0].values())
    assert MARKER not in blob and "system" not in cols[0] and "user" not in cols[0]
    assert cols[0]["pipeline"] == "P-1" and cols[0]["provider"] == "anthropic" and cols[0]["model"] == "claude-sonnet-5-5"
    assert cols[0]["input_tokens"] == 1_000_000 and cols[0]["output_tokens"] == 100_000 and cols[0]["ms"] == 120
    assert cols[0]["at"].startswith(U.month_key())


def test_month_agent_and_run_queries(store):
    month = U.month_key()
    U.record(store, info(), agent="casegen", pipeline="P-1")
    U.record(store, info(model="claude-haiku-5-5", input_tokens=10_000, output_tokens=1_000, tier="cheap"),
             agent="triage", pipeline="P-1")
    U.record(store, info(provider="ollama", model="qwen3:4b", scope="local"), agent="casegen", pipeline="P-2")
    U.record(store, info(at="2026-10-15T10:00:00"), agent="casegen", pipeline="P-0")           # last month
    assert U.month_total(store, month) == pytest.approx(3.0 + 0.0015)
    assert U.month_total(store, "2026-10") == pytest.approx(3.0)
    agents = {a["agent"]: a for a in U.by_agent(store, month)}
    assert agents["casegen"]["calls"] == 2 and agents["casegen"]["cost_usd"] == pytest.approx(3.0)
    assert agents["triage"]["calls"] == 1 and agents["triage"]["cost_usd"] == pytest.approx(0.0015)
    runs = {r["pipeline"]: r for r in U.by_run(store, month)}
    assert set(runs) == {"P-1", "P-2"} and runs["P-2"]["cost_usd"] == 0.0 and runs["P-1"]["calls"] == 2
    s = U.summary(store, month)
    assert s["month"] == month and s["calls"] == 3 and s["total_usd"] == pytest.approx(3.0015)
    assert not s["estimated"]
    U.record(store, info(model="claude-mystery"), agent="srs", pipeline="P-1")
    assert U.summary(store, month)["estimated"]                                 # one estimated row flags the month


def test_month_key_and_a_bad_month_are_safe():
    assert U.month_key("2026-10-15T10:00:00") == "2026-10"
    assert len(U.month_key()) == 7
    with pytest.raises(ValueError):
        U.check_month("2026-13")
    assert U.check_month("2026-01") == "2026-01"


# ---- review fixes (fresh-context reviews, 3 Nov 2026) ------------------------------------------------------

def test_unknown_usage_on_a_cloud_call_is_estimated_high_never_free(store):
    row = U.record(store, info(input_tokens=0, output_tokens=0, usage_known=False, approx_input_tokens=500, max_tokens=700),
                   agent="casegen", pipeline="P-1")
    assert row["estimated"] == 1 and row["cost_usd"] == pytest.approx((500 * 2.0 + 700 * 10.0) / 1_000_000)
    assert row["input_tokens"] == 500 and row["output_tokens"] == 700
    local = U.record(store, info(provider="ollama", model="qwen3:4b", scope="local", input_tokens=0, output_tokens=0,
                                 usage_known=False), agent="casegen", pipeline="P-1")
    assert local["cost_usd"] == 0.0 and local["estimated"] == 0


def test_non_finite_price_overrides_are_ignored():
    prices = {"openai": {"gpt-4o-mini": [float("nan"), 1.0], "gpt-4o": [1.0, float("inf")]}}
    assert U.price_for("openai", "gpt-4o-mini", prices)[:2] == (0.15, 0.60)
    assert U.price_for("openai", "gpt-4o", prices)[:2] == (2.5, 10.0)
