"""M1.2 slice 1: the project's `ai:` block — defaults, migration from the old `llm:` block, validation and saving."""
from __future__ import annotations

import pytest
import yaml

from conftest import ROOT

from agentqa import config, yamledit
from agentqa.ai import settings as S
from agentqa.config import Project

OLD_YAML = """# Old project
project: Old
base_url: http://127.0.0.1:8000

login:
  start: /        # a comment that must survive
  url: /login

llm:
  enabled: {enabled}
  provider: {provider}
  model: qwen3:4b
  max_chunks: 12
  polish_defects: {polish}

visual_qa:
  ask_person: false   # unattended
"""


def write(folder, text: str) -> Project:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "project.yaml").write_text(text, encoding="utf-8")
    return Project(folder)


def test_defaults_have_an_ai_block_and_no_llm_block():
    assert "llm" not in config.DEFAULTS
    ai = config.DEFAULTS["ai"]
    assert ai["mode"] == "none" and ai["consent"] == {"send_text": False, "send_screenshots": False}
    assert ai["budget"] == {"monthly_usd": 10, "alert_at_pct": 80} and ai["assignments"] == {} and ai["max_chunks"] == 40


@pytest.mark.parametrize("enabled,provider,polish,mode,triage", [
    ("false", "ollama", "false", "none", "off"),
    ("true", "ollama", "false", "local", "off"),
    ("true", "gemini", "false", "cloud", "off"),
    ("true", "ollama", "true", "local", None),
])
def test_every_migration_row(tmp_path, enabled, provider, polish, mode, triage):
    p = write(tmp_path, OLD_YAML.format(enabled=enabled, provider=provider, polish=polish))
    ai = p.cfg["ai"]
    assert ai["mode"] == mode
    assert ai["consent"] == {"send_text": False, "send_screenshots": False}          # never carried over
    assert ai["assignments"].get("triage") == triage
    assert ai["max_chunks"] == 12
    assert "llm" not in p.cfg
    assert "llm:" in (tmp_path / "project.yaml").read_text(encoding="utf-8")        # nothing written until a save


def test_a_gemini_project_gets_a_consent_notice_an_ollama_one_does_not(tmp_path):
    gem = write(tmp_path / "g", OLD_YAML.format(enabled="true", provider="gemini", polish="false"))
    notice = S.migration_notice(gem.cfg["ai"])
    assert notice and "consent" in notice.lower()
    oll = write(tmp_path / "o", OLD_YAML.format(enabled="true", provider="ollama", polish="false"))
    assert S.migration_notice(oll.cfg["ai"]) is None


def test_an_existing_ai_block_beats_a_leftover_llm_block(tmp_path):
    text = OLD_YAML.format(enabled="true", provider="gemini", polish="true") + "\nai:\n  mode: local\n  max_chunks: 3\n"
    p = write(tmp_path, text)
    assert p.cfg["ai"]["mode"] == "local" and p.cfg["ai"]["max_chunks"] == 3
    assert p.cfg["ai"]["assignments"] == {}


def test_a_project_without_either_block_uses_the_defaults(tmp_path):
    p = write(tmp_path, "project: Fresh\nbase_url: http://127.0.0.1:1\n")
    assert p.cfg["ai"] == config.DEFAULTS["ai"]


def test_the_demo_project_loads_as_no_ai():
    p = Project(ROOT / "demo")
    assert p.cfg["ai"]["mode"] == "none"


def test_settings_object_is_frozen_validated_and_clamped():
    s = S.AiSettings.from_cfg({"ai": {"mode": "hybrid", "consent": {"send_text": True}, "budget": {"monthly_usd": 2.5},
                                      "assignments": {"triage": "off", "casegen": "strong"}, "max_chunks": 5}})
    assert s.mode == "hybrid" and s.send_text and not s.send_screenshots
    assert s.monthly_usd == 2.5 and s.alert_at_pct == 80 and s.max_chunks == 5
    assert s.tier_for("triage", "cheap") == "off" and s.tier_for("casegen", "balanced") == "strong"
    assert s.tier_for("srs", "balanced") == "balanced"
    with pytest.raises(AttributeError):
        s.mode = "none"            # frozen


@pytest.mark.parametrize("block,word", [
    ({"mode": "turbo"}, "mode"),
    ({"budget": {"monthly_usd": 0}}, "monthly_usd"),
    ({"budget": {"monthly_usd": 5000}}, "monthly_usd"),
    ({"budget": {"alert_at_pct": 0}}, "alert_at_pct"),
    ({"assignments": {"triage": "huge"}}, "triage"),
    ({"assignments": {"nobody": "cheap"}}, "nobody"),
    ({"max_chunks": 0}, "max_chunks"),
])
def test_validation_names_the_bad_field(block, word):
    errors = S.validate({**S.DEFAULT_AI, **block})
    assert errors and word in " ".join(errors)


def test_save_writes_ai_removes_llm_and_keeps_other_comments(tmp_path):
    f = tmp_path / "project.yaml"
    f.write_text(OLD_YAML.format(enabled="true", provider="ollama", polish="false"), encoding="utf-8")
    S.save_ai(f, {"mode": "local", "consent": {"send_text": False, "send_screenshots": False},
                  "budget": {"monthly_usd": 10, "alert_at_pct": 80}, "assignments": {"triage": "off"}, "max_chunks": 12})
    text = f.read_text(encoding="utf-8")
    cfg = yaml.safe_load(text)
    assert "llm" not in cfg and cfg["ai"]["mode"] == "local" and cfg["ai"]["assignments"] == {"triage": "off"}
    assert "# a comment that must survive" in text and "# unattended" in text and "# Old project" in text
    assert Project(tmp_path).cfg["ai"]["mode"] == "local"


def test_remove_top_block_removes_only_that_block(tmp_path):
    f = tmp_path / "project.yaml"
    f.write_text(OLD_YAML.format(enabled="false", provider="ollama", polish="false"), encoding="utf-8")
    assert yamledit.remove_top_block(f, "llm")
    text = f.read_text(encoding="utf-8")
    assert "llm:" not in text and "polish_defects" not in text
    assert yaml.safe_load(text)["visual_qa"] == {"ask_person": False} and "# a comment that must survive" in text
    assert not yamledit.remove_top_block(f, "llm")                 # already gone: nothing to do, nothing written


# ---- review fixes (fresh-context reviews, 3 Nov 2026) ------------------------------------------------------

def test_hand_edited_values_of_the_wrong_shape_fall_back_to_the_defaults():
    assert S.AiSettings.from_cfg({"ai": True}) == S.AiSettings.from_cfg({})
    s = S.AiSettings.from_cfg({"ai": {"mode": "cloud", "budget": "x", "consent": [1], "assignments": [1], "max_chunks": "lots"}})
    assert s.mode == "cloud" and s.monthly_usd == 10 and not s.send_text and s.assignments == () and s.max_chunks == 40
    errors = S.validate({**S.DEFAULT_AI, "budget": "x", "consent": 3, "assignments": [1]})
    assert any("budget" in e for e in errors) and any("consent" in e for e in errors) and any("assignments" in e for e in errors)


def test_consent_is_only_ever_a_real_yes():
    s = S.AiSettings.from_cfg({"ai": {"consent": {"send_text": "false", "send_screenshots": "yes"}}})
    assert not s.send_text and not s.send_screenshots


def test_an_unquoted_yaml_off_still_turns_the_agent_off(tmp_path):
    p = write(tmp_path, "project: Off\nbase_url: http://127.0.0.1:1\nai:\n  mode: local\n  assignments:\n    triage: off\n")
    assert S.AiSettings.from_cfg(p.cfg).tier_for("triage", "cheap") == "off"
    assert S.validate(p.cfg["ai"]) == []
