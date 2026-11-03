"""M1.2 slice 4: the routing table — every mode × tier, consent, hybrid order, agent off, the cap, images."""
from __future__ import annotations

import pytest

from agentqa.ai import modes as M
from agentqa.ai.settings import AiSettings

ALL = {"have_local": True, "have_cloud": True}


def S(mode: str, **kw) -> AiSettings:
    return AiSettings(mode=mode, **kw)


@pytest.mark.parametrize("agent,tier", [("req_chat", "strong"), ("req_writer", "strong"), ("srs", "balanced"),
                                        ("requirements", "balanced"), ("casegen", "balanced"), ("visual_qa", "balanced"),
                                        ("documents", "vision"), ("triage", "cheap"), ("assistant", "cheap"), ("login", "cheap")])
def test_the_default_assignment_table(agent, tier):
    assert M.AGENTS[agent]["tier"] == tier
    assert M.AGENTS[agent]["label"]


def test_no_ai_mode_is_no_ai_for_every_agent():
    for agent in M.AGENTS:
        r = M.resolve(S("none"), agent, **ALL)
        assert r.reason and "off" in r.reason and not r.scopes and not r.enabled


@pytest.mark.parametrize("mode,tier,scopes", [
    ("local", "cheap", ("local",)), ("local", "balanced", ("local",)), ("local", "strong", ("local",)),
    ("cloud", "cheap", ("cloud",)), ("cloud", "balanced", ("cloud",)), ("cloud", "strong", ("cloud",)),
    ("hybrid", "cheap", ("local", "cloud")), ("hybrid", "balanced", ("cloud", "local")), ("hybrid", "strong", ("cloud", "local")),
])
def test_every_mode_times_tier(mode, tier, scopes):
    r = M.resolve(S(mode, send_text=True, assignments=(("casegen", tier),)), "casegen", **ALL)
    assert r.enabled and r.reason is None and r.scopes == scopes and r.tier == tier and r.agent == "casegen"


def test_cloud_without_text_consent_is_no_ai_and_says_why():
    r = M.resolve(S("cloud"), "casegen", **ALL)
    assert not r.enabled and "not allowed text" in r.reason


def test_hybrid_without_text_consent_stays_on_this_computer():
    r = M.resolve(S("hybrid"), "req_writer", **ALL)
    assert r.enabled and r.scopes == ("local",)


def test_an_agent_set_to_off_gets_no_model():
    r = M.resolve(S("local", assignments=(("triage", "off"),)), "triage", **ALL)
    assert not r.enabled and "off" in r.reason and "Defect title polish" in r.reason


def test_the_cap_turns_cloud_off_and_hybrid_local():
    cloud = M.resolve(S("cloud", send_text=True), "casegen", capped=True, **ALL)
    assert not cloud.enabled and "budget" in cloud.reason
    hybrid = M.resolve(S("hybrid", send_text=True), "casegen", capped=True, **ALL)
    assert hybrid.enabled and hybrid.scopes == ("local",)
    local = M.resolve(S("local"), "casegen", capped=True, **ALL)
    assert local.enabled and local.scopes == ("local",)                    # free: the cap does not apply


def test_visual_qa_is_text_only_until_screenshots_are_allowed():
    text_only = M.resolve(S("cloud", send_text=True), "visual_qa", **ALL)
    assert text_only.enabled and not text_only.image and not text_only.need_vision
    with_shots = M.resolve(S("cloud", send_text=True, send_screenshots=True), "visual_qa", **ALL)
    assert with_shots.enabled and with_shots.image and not with_shots.need_vision
    local = M.resolve(S("local"), "visual_qa", **ALL)
    assert local.enabled and not local.image                                 # qwen3 cannot see: text only


def test_ocr_needs_a_model_that_can_see_the_image():
    assert "image" in M.resolve(S("local"), "documents", **ALL).reason
    assert "image" in M.resolve(S("cloud", send_text=True), "documents", **ALL).reason
    ok = M.resolve(S("cloud", send_text=True, send_screenshots=True), "documents", **ALL)
    assert ok.enabled and ok.image and ok.need_vision and ok.scopes == ("cloud",)
    assert "image" in M.resolve(S("hybrid", send_text=True), "documents", **ALL).reason
    seen = M.resolve(S("local"), "documents", have_local=True, have_cloud=False, local_vision=True)
    assert seen.enabled and seen.image and seen.need_vision


def test_no_usable_key_gives_a_plain_english_reason():
    r = M.resolve(S("local"), "casegen", have_local=False, have_cloud=True)
    assert not r.enabled and "Ollama" in r.reason and "LM Studio" in r.reason
    r = M.resolve(S("cloud", send_text=True), "casegen", have_local=True, have_cloud=False)
    assert not r.enabled and "key" in r.reason
    r = M.resolve(S("hybrid", send_text=True), "casegen", have_local=False, have_cloud=False)
    assert not r.enabled
    r = M.resolve(S("hybrid"), "casegen", have_local=False, have_cloud=True)          # consent off, nothing local
    assert not r.enabled and "Ollama" in r.reason


def test_an_unknown_agent_is_a_programming_error():
    with pytest.raises(KeyError):
        M.resolve(S("local"), "nobody", **ALL)


def test_the_effective_table_covers_every_agent():
    rows = M.effective(S("hybrid", send_text=True, assignments=(("triage", "off"),)), **ALL)
    assert [r.agent for r in rows] == list(M.AGENTS)
    by = {r.agent: r for r in rows}
    assert by["triage"].reason and by["casegen"].scopes == ("cloud", "local") and by["login"].scopes == ("local", "cloud")


# ---- review fixes (fresh-context reviews, 3 Nov 2026) ------------------------------------------------------

@pytest.mark.parametrize("agent", ["visual_qa", "documents"])
def test_hybrid_without_screenshot_consent_keeps_images_on_this_computer(agent):
    s = S("hybrid", send_text=True, send_screenshots=False)
    seen = M.resolve(s, agent, have_local=True, have_cloud=True, local_vision=True)
    assert seen.enabled and seen.scopes == ("local",) and seen.image           # never a cloud key with the image
    blind = M.resolve(s, agent, have_local=True, have_cloud=True, local_vision=False)
    if agent == "visual_qa":
        assert blind.enabled and blind.scopes == ("cloud", "local") and not blind.image      # text only, cloud first
    else:
        assert not blind.enabled and "image" in blind.reason
    allowed = M.resolve(S("hybrid", send_text=True, send_screenshots=True), agent, have_local=True, have_cloud=True)
    assert allowed.enabled and allowed.scopes == ("cloud", "local") and allowed.image


def test_the_settings_agent_keys_match_the_assignment_table():
    from agentqa.ai.settings import AGENT_KEYS
    assert set(AGENT_KEYS) == set(M.AGENTS)
