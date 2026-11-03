"""AI provider gateway: many providers, several keys each, automatic failover, and per-project AI modes.

    from agentqa.ai.client import model_for
    llm = model_for(project, "casegen")          # None when the project's mode, consent, budget or keys say no AI
    data = llm.chat_json(system, user) if llm else None

Keys and the routing policy are kept once per installation (not per project), encrypted with the same
per-user key as the test data vault: %APPDATA%\\AgentQA on Windows, ~/.agentqa elsewhere, or
AGENTQA_HOME. Key health and the audit log of every failure and switch live beside them in ai.db.
Token usage and cost live in each project's own store (ai_usage).

The names below are loaded lazily (PEP 562): `agentqa.config` imports `agentqa.ai.settings` on every project
load and must not pay for the provider SDKs the router pulls in.
"""
from __future__ import annotations

__all__ = ["AIStore", "Gateway", "agentqa_home", "gateway"]

_LAZY = {"Gateway": "agentqa.ai.router", "gateway": "agentqa.ai.router",
         "AIStore": "agentqa.ai.store", "agentqa_home": "agentqa.ai.store"}


def __getattr__(name: str):
    if name in _LAZY:
        import importlib
        return getattr(importlib.import_module(_LAZY[name]), name)
    raise AttributeError(f"module 'agentqa.ai' has no attribute {name!r}")
