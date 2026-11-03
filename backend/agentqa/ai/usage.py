"""Token usage and cost, kept in the **project's** store (ai_usage): what each agent, each run and each month cost.

A row holds numbers and names only — provider, model, tokens, dollars, milliseconds — never a word of any prompt
or answer. Local models cost $0. A cloud model missing from the price table is charged at its provider's highest
known price and flagged `estimated`, so the meter errs on the high side and says so.

DEFAULT_PRICES is USD per million tokens (input, output), copied from the vendors' price pages on PRICES_DATED. The
owner can override or extend it under the AI policy's `prices` ({provider: {model: [in, out]}}).
"""
from __future__ import annotations

import math
import re
import time

PRICES_DATED = "2026-11-03"
# Anthropic: platform.claude.com/docs/en/about-claude/pricing (Haiku 5.5 is $0.50 / $2.50 for prompts over 100K tokens;
# AgentQA's prompts are far smaller). Gemini: aistudio.google.com/docs/pricing paid tier (3.8 Flash rises to $1.50 /
# $7.50 on 1 Jan 2027). OpenAI: developers.openai.com/api/docs/pricing standard tier.
DEFAULT_PRICES: dict[str, dict[str, tuple[float, float]]] = {
    "anthropic": {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)},
    "gemini": {"gemini-flash-lite-latest": (0.30, 2.50), "gemini-3.5-flash-lite": (0.30, 2.50),
               "gemini-flash-latest": (0.75, 3.75), "gemini-3.8-flash": (0.75, 3.75),
               "gemini-pro-latest": (2.0, 12.0), "gemini-3.1-pro-preview": (2.0, 12.0)},
    "openai": {"gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.50, 10.0), "gpt-4.1-mini": (0.40, 1.60)},
}
TABLE = "ai_usage"
SCHEMA = f"""CREATE TABLE IF NOT EXISTS {TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, pipeline TEXT, agent TEXT, tier TEXT, scope TEXT, provider TEXT,
    model TEXT, input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL, estimated INTEGER, ms INTEGER)"""
COLUMNS = ("at", "pipeline", "agent", "tier", "scope", "provider", "model", "input_tokens", "output_tokens", "cost_usd",
           "estimated", "ms")
MILLION = 1_000_000
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def month_key(at: str | None = None) -> str:
    """'YYYY-MM' of an ISO timestamp, or of now."""
    return (at or time.strftime("%Y-%m-%dT%H:%M:%S"))[:7]


def check_month(month: str) -> str:
    if not MONTH_RE.match(month or ""):
        raise ValueError("month must look like 2026-11")
    return month


def merged_prices(overrides: dict | None) -> dict[str, dict[str, tuple[float, float]]]:
    out = {p: dict(models) for p, models in DEFAULT_PRICES.items()}
    for provider, models in (overrides or {}).items():
        if not isinstance(models, dict):
            continue
        table = out.setdefault(str(provider), {})
        for model, pair in models.items():
            try:
                price_in, price_out = float(pair[0]), float(pair[1])
            except (TypeError, ValueError, IndexError, KeyError):
                continue                               # a malformed override never breaks the meter
            if math.isfinite(price_in) and math.isfinite(price_out) and price_in >= 0 and price_out >= 0:
                table[str(model)] = (price_in, price_out)
    return out


def _highest(tables: list[dict[str, tuple[float, float]]]) -> tuple[float, float]:
    pairs = [pair for t in tables for pair in t.values()]
    return max(pairs, key=lambda p: (p[1], p[0])) if pairs else (0.0, 0.0)


def price_for(provider: str, model: str, prices: dict | None = None, scope: str = "cloud") -> tuple[float, float, bool]:
    """(usd per 1M input tokens, usd per 1M output tokens, estimated). Local models are free."""
    if scope == "local":
        return 0.0, 0.0, False
    table = merged_prices(prices)
    known = table.get(provider, {})
    if model in known:
        return known[model][0], known[model][1], False
    high = _highest([known] if known else list(table.values()))
    return high[0], high[1], True


def cost_usd(provider: str, model: str, input_tokens: int, output_tokens: int, prices: dict | None = None,
             scope: str = "cloud") -> tuple[float, bool]:
    inp, out, estimated = price_for(provider, model, prices, scope)
    return (int(input_tokens or 0) * inp + int(output_tokens or 0) * out) / MILLION, estimated


def ensure(store) -> None:
    store.exec(SCHEMA)


def record(store, info: dict, *, agent: str, pipeline: str | None, prices: dict | None = None) -> dict:
    """Write one usage row from the router's `on_usage` payload; only the known columns are kept. A cloud call whose
    provider reported no usage is charged for the prompt size and the whole max_tokens, and flagged estimated."""
    ensure(store)
    scope = str(info.get("scope") or "cloud")
    tokens_in, tokens_out = int(info.get("input_tokens") or 0), int(info.get("output_tokens") or 0)
    unknown = info.get("usage_known") is False and scope != "local"
    if unknown:
        tokens_in, tokens_out = int(info.get("approx_input_tokens") or 0), int(info.get("max_tokens") or 0)
    cost, estimated = cost_usd(str(info.get("provider") or ""), str(info.get("model") or ""), tokens_in, tokens_out, prices, scope)
    row = {"at": str(info.get("at") or time.strftime("%Y-%m-%dT%H:%M:%S")), "pipeline": pipeline or "single",
           "agent": agent, "tier": info.get("tier"), "scope": scope, "provider": info.get("provider"),
           "model": info.get("model"), "input_tokens": tokens_in, "output_tokens": tokens_out, "cost_usd": round(cost, 8),
           "estimated": int(bool(estimated) or unknown), "ms": info.get("ms")}
    store.insert(TABLE, {c: row[c] for c in COLUMNS})
    return row


def _where(month: str) -> tuple[str, list]:
    return "WHERE at >= ? AND at < ?", [f"{month}-01", _next_month(month)]


def _next_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y + (m // 12)}-{(m % 12) + 1:02d}-01"


def month_total(store, month: str) -> float:
    ensure(store)
    cond, params = _where(month)
    return float(store.scalar(f"SELECT COALESCE(SUM(cost_usd), 0) FROM {TABLE} {cond}", params) or 0.0)


GROUP_COLUMNS = ("agent", "pipeline")


def _grouped(store, month: str, column: str) -> list[dict]:
    assert column in GROUP_COLUMNS            # the identifier is interpolated: only these two, never user input
    ensure(store)
    cond, params = _where(month)
    return store.all(f"SELECT {column}, COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost_usd, "
                     f"COALESCE(SUM(input_tokens), 0) AS input_tokens, COALESCE(SUM(output_tokens), 0) AS output_tokens, "
                     f"MAX(estimated) AS estimated, MAX(at) AS last_at FROM {TABLE} {cond} GROUP BY {column} "
                     f"ORDER BY cost_usd DESC, {column}", params)


def by_agent(store, month: str) -> list[dict]:
    return [{**r, "estimated": bool(r["estimated"])} for r in _grouped(store, month, "agent")]


def by_run(store, month: str) -> list[dict]:
    return [{**r, "estimated": bool(r["estimated"])} for r in _grouped(store, month, "pipeline")]


def summary(store, month: str) -> dict:
    agents = by_agent(store, month)
    return {"month": month, "prices_dated": PRICES_DATED, "total_usd": round(sum(a["cost_usd"] for a in agents), 6),
            "calls": sum(a["calls"] for a in agents), "estimated": any(a["estimated"] for a in agents),
            "agents": agents, "runs": by_run(store, month)}
