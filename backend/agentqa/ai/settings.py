"""The project's `ai:` block: defaults, migration from the old `llm:` block, validation and saving.

Pure: no provider SDK, no network. `agentqa.config` imports this on every project load.

    ai:
      mode: none            # none | local | cloud | hybrid
      consent: {send_text: false, send_screenshots: false}   # only matter when text would leave the PC
      budget: {monthly_usd: 10, alert_at_pct: 80}            # 0.5-1000; there is no "unlimited"
      assignments: {}       # agent: cheap|balanced|strong|vision|off, overrides the default table
      max_chunks: 40        # was llm.max_chunks (Requirement Analyst model pass)
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

import yaml

MODES = ("none", "local", "cloud", "hybrid")
TIER_CHOICES = ("cheap", "balanced", "strong", "vision", "off")
# Agent keys that may appear in `assignments` (the default tiers live in ai/modes.py, which may import the SDKs).
AGENT_KEYS = ("req_chat", "req_writer", "srs", "requirements", "casegen", "visual_qa", "documents", "triage",
              "assistant", "login")
MIN_BUDGET_USD, MAX_BUDGET_USD = 0.5, 1000.0
MIN_CHUNKS, MAX_CHUNKS = 1, 500
MIGRATED_GEMINI = "llm:gemini"

DEFAULT_AI: dict = {
    "mode": "none",
    "consent": {"send_text": False, "send_screenshots": False},
    "budget": {"monthly_usd": 10, "alert_at_pct": 80},
    "assignments": {},
    "max_chunks": 40,
}


def migrate_llm(raw: dict) -> dict:
    """A copy of the raw project.yaml mapping with the old `llm:` block expressed as `ai:` (when `ai:` is missing).

    missing or enabled: false -> none · enabled + ollama -> local · enabled + gemini -> cloud with consent OFF and a
    notice (the old code sent text to Google without asking; the project's own Gemini key is not carried over) ·
    polish_defects false (the old default) -> triage off · max_chunks kept. Nothing is written to disk here."""
    if not isinstance(raw, dict) or "ai" in raw or not isinstance(raw.get("llm"), dict):
        return raw
    old = raw["llm"]
    enabled = bool(old.get("enabled"))
    provider = str(old.get("provider") or "ollama").lower()
    ai = copy.deepcopy(DEFAULT_AI)
    ai["mode"] = "none" if not enabled else ("cloud" if provider == "gemini" else "local")
    if not old.get("polish_defects", False):
        ai["assignments"] = {"triage": "off"}
    if "max_chunks" in old:
        ai["max_chunks"] = old["max_chunks"]
    if enabled and provider == "gemini":
        ai["migrated_from"] = MIGRATED_GEMINI
    out = dict(raw)
    out["ai"] = ai
    return out


def migration_notice(ai: dict) -> str | None:
    if (ai or {}).get("migrated_from") == MIGRATED_GEMINI:
        return ("Confirm the consent switches: this project used Google Gemini before. Sending text to a cloud provider "
                "now needs your consent, and the project's own Gemini key is not carried over: add it under AI providers.")
    return None


@dataclass(frozen=True)
class AiSettings:
    mode: str = "none"
    send_text: bool = False
    send_screenshots: bool = False
    monthly_usd: float = 10.0
    alert_at_pct: int = 80
    assignments: tuple[tuple[str, str], ...] = ()
    max_chunks: int = 40

    @classmethod
    def from_cfg(cls, cfg: dict) -> "AiSettings":
        """From a project's merged cfg (or anything with an `ai` key). Unknown values fall back to the defaults."""
        ai = {**DEFAULT_AI, **_mapping((cfg or {}).get("ai"))}
        consent = {**DEFAULT_AI["consent"], **_mapping(ai.get("consent"))}
        budget = {**DEFAULT_AI["budget"], **_mapping(ai.get("budget"))}
        mode = str(ai.get("mode") or "none").lower()
        assigns = tuple((str(k), _tier(v)) for k, v in _mapping(ai.get("assignments")).items() if _tier(v) in TIER_CHOICES)
        return cls(mode=mode if mode in MODES else "none", send_text=consent.get("send_text") is True,
                   send_screenshots=consent.get("send_screenshots") is True,
                   monthly_usd=_clamp(budget.get("monthly_usd"), MIN_BUDGET_USD, MAX_BUDGET_USD, 10.0),
                   alert_at_pct=int(_clamp(budget.get("alert_at_pct"), 1, 100, 80)),
                   assignments=assigns, max_chunks=int(_clamp(ai.get("max_chunks"), MIN_CHUNKS, MAX_CHUNKS, 40)))

    def tier_for(self, agent: str, default: str) -> str:
        return dict(self.assignments).get(agent, default)

    def enabled(self) -> bool:
        return self.mode != "none"


def _mapping(value) -> dict:
    """A hand-edited project.yaml may hold anything; only a mapping counts."""
    return value if isinstance(value, dict) else {}


def _tier(value) -> str:
    """PyYAML reads an unquoted `off` as False: that still means off."""
    return "off" if value is False else str(value).lower()


def _clamp(value, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return min(hi, max(lo, v))


def _number(value, lo: float, hi: float) -> bool:
    try:
        return lo <= float(value) <= hi
    except (TypeError, ValueError):
        return False


def validate(block: dict) -> list[str]:
    """Plain-English problems with an `ai:` block (empty when it is fine). The API uses pydantic first; this is the
    second check for anything written by hand into project.yaml."""
    errors: list[str] = []
    if not isinstance(block, dict):
        return ["the ai block must be a mapping"]
    if str(block.get("mode", "none")).lower() not in MODES:
        errors.append(f"mode must be one of {', '.join(MODES)}")
    for field in ("budget", "consent", "assignments"):
        if field in block and not isinstance(block[field], dict):
            errors.append(f"{field} must be a mapping (name: value lines)")
    budget = _mapping(block.get("budget"))
    if not _number(budget.get("monthly_usd", 10), MIN_BUDGET_USD, MAX_BUDGET_USD):
        errors.append(f"budget.monthly_usd must be between {MIN_BUDGET_USD} and {MAX_BUDGET_USD:.0f}")
    if not _number(budget.get("alert_at_pct", 80), 1, 100):
        errors.append("budget.alert_at_pct must be between 1 and 100")
    for agent, tier in _mapping(block.get("assignments")).items():
        if agent not in AGENT_KEYS:
            errors.append(f"assignments: '{agent}' is not an agent (choose from {', '.join(AGENT_KEYS)})")
        elif _tier(tier) not in TIER_CHOICES:
            errors.append(f"assignments.{agent} must be one of {', '.join(TIER_CHOICES)}")
    if not _number(block.get("max_chunks", 40), MIN_CHUNKS, MAX_CHUNKS):
        errors.append(f"max_chunks must be between {MIN_CHUNKS} and {MAX_CHUNKS}")
    return errors


def save_ai(path: Path, block: dict) -> None:
    """Write the `ai:` block into project.yaml (comments elsewhere survive) and remove the old `llm:` block."""
    from agentqa import yamledit
    errors = validate(block)
    if errors:
        raise ValueError("; ".join(errors))
    clean = {k: v for k, v in block.items() if k != "migrated_from"}
    yamledit.replace_top_block(path, "ai", yaml.safe_dump({"ai": clean}, sort_keys=False))
    yamledit.remove_top_block(path, "llm")
