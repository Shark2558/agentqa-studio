"""AI provider gateway: many providers, several keys each, automatic failover.

    from agentqa.ai import gateway
    data = gateway().complete_json(system, user, task="srs")      # dict, or None when every key failed

Keys and the routing policy are kept once per installation (not per project), encrypted with the same
per-user key as the test data vault: %APPDATA%\\AgentQA on Windows, ~/.agentqa elsewhere, or
AGENTQA_HOME. Key health and the audit log of every failure and switch live beside them in ai.db.
"""
from agentqa.ai.router import Gateway, gateway
from agentqa.ai.store import AIStore, agentqa_home

__all__ = ["AIStore", "Gateway", "agentqa_home", "gateway"]
