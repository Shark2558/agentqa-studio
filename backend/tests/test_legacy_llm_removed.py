"""M1.2: the old per-project model client is gone; the AI gateway (agentqa.ai) is the only door."""
from __future__ import annotations

import importlib

import pytest

from conftest import ROOT


def test_the_old_module_cannot_be_imported():
    with pytest.raises(ImportError):
        importlib.import_module("agentqa.llm")


def test_no_source_file_mentions_the_old_module():
    offenders = []
    for folder in ("agentqa", "demo", "tools"):
        for f in (ROOT / folder).rglob("*.py"):
            text = f.read_text(encoding="utf-8", errors="replace")
            if "agentqa.llm" in text or "from agentqa import llm" in text or "LocalLLM" in text or "GeminiLLM" in text:
                offenders.append(str(f.relative_to(ROOT)))
    assert offenders == []


def test_the_cli_has_ai_test_but_no_llm_check():
    from agentqa import cli
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "cmd")
    assert "ai-test" in sub.choices and "llm-check" not in sub.choices


def test_project_defaults_and_the_dashboard_speak_ai_not_llm():
    from agentqa import config
    assert "llm" not in config.DEFAULTS
    app = (ROOT / "agentqa" / "web" / "app.py").read_text(encoding="utf-8")
    assert 'cfg.get("llm"' not in app and "testdata/model" not in app
    testdata = (ROOT / "agentqa" / "web" / "templates" / "testdata.html").read_text(encoding="utf-8")
    assert "gemini_model" not in testdata and "Project model fallback" not in testdata
