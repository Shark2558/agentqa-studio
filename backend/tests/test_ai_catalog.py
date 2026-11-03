"""M1.2 slice 1: the provider catalogue, local detection and the tier table (agents ask for a tier, never a model)."""
from __future__ import annotations

import pytest

from agentqa.ai import catalog as C
from agentqa.ai import providers as P

CLAUDE = ["claude-3-5-haiku-20241022", "claude-opus-5-5", "claude-sonnet-4-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
GEMINI = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.8-flash", "gemini-flash-lite-latest", "gemini-flash-latest",
          "gemini-pro-latest", "gemini-2.5-flash-preview-tts", "gemini-3-flash-preview"]


def key(provider: str, **kw) -> dict:
    return {"provider": provider, "label": provider, "key": "k", "model": "auto", **kw}


def test_catalog_is_shared_with_the_adapters_and_has_both_local_providers():
    assert P.CATALOG is C.CATALOG
    assert C.CATALOG["ollama"]["local"] and C.CATALOG["ollama"]["keyless"]
    lm = C.CATALOG["lmstudio"]
    assert lm["local"] and lm["keyless"] and lm["family"] == "openai" and lm["base_url"] == "http://127.0.0.1:1234/v1"
    assert not C.CATALOG["anthropic"].get("local") and not C.CATALOG["openai_compatible"].get("local")


@pytest.mark.parametrize("tier,model", [("cheap", "claude-haiku-5-5"), ("balanced", "claude-sonnet-5-5"),
                                        ("strong", "claude-opus-5-5"), ("vision", "claude-sonnet-5-5")])
def test_anthropic_tiers(tier, model):
    assert C.model_for_tier(key("anthropic"), CLAUDE, tier) == model


def test_a_pinned_model_wins_over_the_tier():
    assert C.model_for_tier(key("gemini", model="gemini-flash-lite-latest"), GEMINI, "strong") == "gemini-flash-lite-latest"
    assert C.models_for_tier(key("anthropic", model="claude-haiku-5-5", fallback_model="claude-sonnet-5-5"), CLAUDE, "strong") \
        == ["claude-haiku-5-5", "claude-sonnet-5-5"]


def test_gemini_tiers_prefer_the_latest_aliases_with_the_next_as_a_candidate():
    assert C.models_for_tier(key("gemini"), GEMINI, "cheap")[:2] == ["gemini-flash-lite-latest", "gemini-flash-latest"]
    assert C.models_for_tier(key("gemini"), GEMINI, "strong")[:2] == ["gemini-pro-latest", "gemini-flash-latest"]
    assert C.model_for_tier(key("gemini"), GEMINI, "vision") == "gemini-flash-lite-latest"


def test_gemini_auto_pick_takes_an_alias_and_never_the_newest_number():
    assert C.gemini_pick(GEMINI) == "gemini-flash-latest"
    assert C.gemini_pick([n for n in GEMINI if not n.endswith("-latest")]) == "gemini-2.5-flash"     # not gemini-3.8-flash
    # port of the v0.5 assertions: the stable flash, never lite, tts, embeddings or previews
    assert C.gemini_pick(["gemini-2.0-flash-lite", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-preview-tts",
                          "text-embedding-004"]) == "gemini-2.5-flash"
    assert C.gemini_pick(["text-embedding-004"]) is None
    assert P.adapter(key("gemini", base_url="http://127.0.0.1:9/v1beta"), timeout=1).pick(GEMINI) == "gemini-flash-latest"


def test_parse_json_accepts_a_fenced_answer_and_wraps_a_list():
    assert P.parse_json('```json\n{"cases": [{"title": "x"}]}\n```') == {"cases": [{"title": "x"}]}
    assert P.parse_json("[1, 2]") == {"items": [1, 2]} and P.parse_json("not json") is None


def test_tier_candidates_fall_back_to_the_providers_own_pick_when_none_is_listed():
    assert C.models_for_tier(key("anthropic"), ["claude-sonnet-4-5"], "strong") == ["claude-sonnet-4-5"]
    assert C.models_for_tier(key("openai"), ["gpt-4o", "gpt-4o-mini"], "strong") == ["gpt-4o-mini"]
    assert C.models_for_tier(key("anthropic"), [], "strong") == ["claude-opus-5-5"]       # nothing listed yet: trust the table


def test_local_keys_use_their_own_model_for_every_tier():
    k = key("ollama", base_url="http://127.0.0.1:11434")
    for tier in C.TIER_NAMES:
        assert C.model_for_tier(k, ["qwen3:4b", "llama3:8b"], tier) == "qwen3:4b"
    assert C.model_for_tier(key("lmstudio", base_url="http://127.0.0.1:1234/v1"), ["some-gguf"], "strong") == "some-gguf"


def test_local_means_a_local_provider_on_a_loopback_address():
    assert C.is_local(key("ollama", base_url="http://127.0.0.1:11434"))
    assert C.is_local(key("ollama", base_url="http://localhost:11434"))
    assert C.is_local(key("lmstudio"))                                      # the catalogue address is loopback
    assert not C.is_local(key("ollama", base_url="http://10.0.0.5:11434"))  # another machine: treated as cloud
    assert not C.is_local(key("openai_compatible", base_url="http://127.0.0.1:8000/v1"))   # not a local provider
    assert C.scope_of(key("anthropic")) == "cloud" and C.scope_of(key("ollama")) == "local"


def test_the_public_catalog_view_never_includes_internals():
    rows = C.public()
    lm = next(r for r in rows if r["id"] == "lmstudio")
    assert lm["local"] and lm["keyless"] and lm["family"] == "openai" and "prefer" not in lm
    assert {r["id"] for r in rows} >= {"openai", "anthropic", "gemini", "ollama", "lmstudio"}
    assert set(C.TIERS["anthropic"]) == set(C.TIER_NAMES)


# ---- review fixes (fresh-context reviews, 3 Nov 2026) ------------------------------------------------------

def test_a_local_key_can_see_only_with_a_vision_model():
    assert C.can_see(key("ollama", base_url="http://127.0.0.1:11434", model="llava:7b"))
    assert C.can_see(key("ollama", base_url="http://127.0.0.1:11434", model="qwen2.5vl:7b"))
    assert not C.can_see(key("ollama", base_url="http://127.0.0.1:11434", model="qwen3:4b"))
    assert not C.can_see(key("lmstudio"))                                   # model auto, nothing says it can see
    assert C.can_see(key("anthropic")) and not C.can_see(key("deepseek"))


def test_gemini_versions_compare_as_numbers_not_decimals():
    assert C.gemini_pick(["gemini-2.10-flash", "gemini-2.5-flash"]) == "gemini-2.5-flash"
