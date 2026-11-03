"""The provider catalogue and the tier table.

Agents ask for a *tier* (cheap / balanced / strong / vision), never a model id. The tier table maps a tier to the
model names a provider offers, in order of preference; a key whose `model` is pinned (not `auto`) wins over the
tier. Local providers (Ollama, LM Studio) have one model per key, used for every tier.

"Local" means the provider is marked local **and** its address is this computer (loopback). An Ollama on another
machine is treated as cloud: text would leave the PC, so it needs consent.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

CATALOG: dict[str, dict] = {
    "openai": {"name": "OpenAI", "family": "openai", "base_url": "https://api.openai.com/v1",
               "prefer": [r"^gpt-4o-mini$", r"^gpt-4\.1-mini", r"^gpt-4o$", r"mini"], "vision": True},
    "anthropic": {"name": "Anthropic Claude", "family": "anthropic", "base_url": "https://api.anthropic.com/v1",
                  "prefer": [r"^claude-sonnet-5-5$", r"^claude-haiku-5-5$", r"^claude-opus-5-5$", r"sonnet", r"haiku", r"claude"],
                  "vision": True},
    "gemini": {"name": "Google Gemini", "family": "gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta",
               "prefer": [], "vision": True},
    "deepseek": {"name": "DeepSeek", "family": "openai", "base_url": "https://api.deepseek.com/v1",
                 "prefer": [r"^deepseek-chat$", r"chat"], "vision": False},
    "groq": {"name": "Groq", "family": "openai", "base_url": "https://api.groq.com/openai/v1",
             "prefer": [r"llama-3\.3-70b", r"llama", r"qwen"], "vision": False},
    "mistral": {"name": "Mistral AI", "family": "openai", "base_url": "https://api.mistral.ai/v1",
                "prefer": [r"^mistral-small-latest$", r"mistral-small", r"mistral-medium", r"latest"], "vision": False},
    "openrouter": {"name": "OpenRouter", "family": "openai", "base_url": "https://openrouter.ai/api/v1",
                   "prefer": [], "vision": True},
    "azure_openai": {"name": "Azure OpenAI", "family": "azure", "base_url": "https://<resource>.openai.azure.com",
                     "prefer": [], "vision": True},
    "openai_compatible": {"name": "OpenAI-compatible (custom URL)", "family": "openai", "base_url": "",
                          "prefer": [], "vision": False},
    "ollama": {"name": "Ollama (local)", "family": "ollama", "base_url": "http://127.0.0.1:11434",
               "prefer": [r"qwen3", r"qwen2\.5", r"llama3"], "vision": False, "keyless": True, "local": True},
    "lmstudio": {"name": "LM Studio (local)", "family": "openai", "base_url": "http://127.0.0.1:1234/v1",
                 "prefer": [], "vision": False, "keyless": True, "local": True},
}

TIER_NAMES = ("cheap", "balanced", "strong", "vision")
# Per provider: tier -> model names in order of preference. Only used for keys whose model is `auto`.
# Gemini's `-latest` aliases are Google's own "current model" pointers; the numbered 3.x flash timed out in M0.3.
TIERS: dict[str, dict[str, list[str]]] = {
    "anthropic": {"cheap": ["claude-haiku-5-5"], "balanced": ["claude-sonnet-5-5"], "strong": ["claude-opus-5-5"],
                  "vision": ["claude-sonnet-5-5"]},
    "gemini": {"cheap": ["gemini-flash-lite-latest", "gemini-flash-latest"],
               "balanced": ["gemini-flash-lite-latest", "gemini-flash-latest"],
               "strong": ["gemini-pro-latest", "gemini-flash-latest"],
               "vision": ["gemini-flash-lite-latest", "gemini-flash-latest"]},
}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
PUBLIC_FIELDS = ("name", "family", "base_url", "vision", "keyless", "local")

_SKIP_GEMINI = re.compile(r"(lite|tts|image|live|audio|embed|vision|aqa|imagen|veo|transcribe|omni|nano|banana|learnlm|gemma|"
                          r"thinking|exp|computer|robotics)", re.I)
_GEMINI_ALIASES = ("gemini-flash-latest", "gemini-flash-lite-latest", "gemini-pro-latest")
_STABLE_FLASH = re.compile(r"^gemini-(\d+(?:\.\d+)?)-flash$")
# Local models that can read images (Ollama / LM Studio name them this way); cloud providers carry a catalogue flag.
LOCAL_VISION = re.compile(r"(llava|vl\b|vl[:-]|vision|minicpm-v|moondream|bakllava|gemma3|pixtral)", re.I)


def base_url(key: dict) -> str:
    return str(key.get("base_url") or CATALOG.get(key.get("provider", ""), {}).get("base_url") or "").rstrip("/")


def is_local(key: dict) -> bool:
    """A local provider on a loopback address: nothing leaves this computer."""
    if not CATALOG.get(key.get("provider", ""), {}).get("local"):
        return False
    host = (urlsplit(base_url(key)).hostname or "").lower()
    return host in LOOPBACK_HOSTS


def scope_of(key: dict) -> str:
    return "local" if is_local(key) else "cloud"


def can_see(key: dict) -> bool:
    """May an image go to this key? Cloud providers: the catalogue says. Local keys: only a vision model by name."""
    spec = CATALOG.get(key.get("provider", ""), {})
    if spec.get("local"):
        return bool(LOCAL_VISION.search(str(key.get("model") or "")))
    return bool(spec.get("vision"))


def prefer_pick(provider: str, names: list[str]) -> str | None:
    """The generic auto-pick: the first `prefer` pattern that matches, else the first name listed."""
    for pat in CATALOG.get(provider, {}).get("prefer", []):
        hits = sorted(n for n in names if re.search(pat, n))
        if hits:
            return hits[0]
    return names[0] if names else None


def gemini_pick(names: list[str]) -> str | None:
    """Gemini auto-pick: Google's `-latest` aliases first. Without them, the lowest-numbered stable flash model
    (the proven one; M0.3 found the newest number timing out), then any flash, then any text model. Never by
    highest version, never lite / tts / embeddings / previews when something plain is listed."""
    for alias in _GEMINI_ALIASES:
        if alias in names:
            return alias

    def ver(n: str) -> tuple[int, ...]:
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)
    stable = [n for n in names if _STABLE_FLASH.match(n)]
    if stable:
        return min(stable, key=ver)
    flash = [n for n in names if "flash" in n and not _SKIP_GEMINI.search(n) and "preview" not in n]
    flash = flash or [n for n in names if "flash" in n and not _SKIP_GEMINI.search(n)]
    pool = flash or [n for n in names if n.startswith("gemini") and not _SKIP_GEMINI.search(n)]
    return min(pool, key=lambda n: (ver(n), len(n))) if pool else None


def pick(provider: str, names: list[str]) -> str | None:
    return gemini_pick(names) if CATALOG.get(provider, {}).get("family") == "gemini" else prefer_pick(provider, names)


def models_for_tier(key: dict, names: list[str], tier: str | None) -> list[str]:
    """Candidate models for this key and tier, in the order the router tries them (a pinned model wins; the key's
    fallback model comes last). Empty when nothing at all can be chosen."""
    pinned = str(key.get("model") or "auto")
    out: list[str] = []
    if pinned != "auto":
        out.append(pinned)
    elif not is_local(key) and tier in TIERS.get(key.get("provider", ""), {}):
        out += [m for m in TIERS[key["provider"]][tier] if not names or m in names]
    if not out:
        chosen = pick(key.get("provider", ""), names)
        if chosen:
            out.append(chosen)
    fb = key.get("fallback_model")
    if fb and fb not in out:
        out.append(fb)
    return out


def model_for_tier(key: dict, names: list[str], tier: str | None) -> str | None:
    cands = models_for_tier(key, names, tier)
    return cands[0] if cands else None


def public() -> list[dict]:
    """The catalogue for the API and the pages: ids, names and flags, never the matching patterns."""
    return [{"id": pid, **{f: spec.get(f, False) if f in ("vision", "keyless", "local") else spec.get(f, "")
                           for f in PUBLIC_FIELDS}, "tiers": TIERS.get(pid, {})} for pid, spec in CATALOG.items()]
