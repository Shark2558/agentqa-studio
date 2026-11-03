"""Is a local model server running on this computer? Two fixed loopback addresses, one second each, no parameters.

The owner cannot point this at another machine: an Ollama elsewhere is a cloud key (text would leave the PC). Each
outcome comes with a plain-English fix; a running server with a model offers the address for "Use it" (which is
POST /ai/keys with that fixed address).
"""
from __future__ import annotations

import time

import httpx

PROBES: tuple[tuple[str, str], ...] = (("ollama", "http://127.0.0.1:11434/api/tags"),
                                       ("lmstudio", "http://127.0.0.1:1234/v1/models"))
TIMEOUT_S = 1.0
SUGGESTED_MODEL = "qwen3:4b"
NAMES = {"ollama": "Ollama (local)", "lmstudio": "LM Studio (local)"}
FIX_NOT_RUNNING = {
    "ollama": "Ollama is not running on this computer. Install it from https://ollama.com, start it, then come back here.",
    "lmstudio": "LM Studio is not running, or its local server is off. Start LM Studio, open the Developer tab and switch "
                "the server on (port 1234).",
}
FIX_NO_MODEL = {
    "ollama": f"Ollama is running but no model is pulled. Open a terminal and run: ollama pull {SUGGESTED_MODEL}",
    "lmstudio": "LM Studio is running but no model is loaded. Load one in LM Studio, then come back here.",
}
LIST_PATH = {"ollama": "/api/tags", "lmstudio": "/models"}


def _names(provider: str, data) -> list[str]:
    if not isinstance(data, dict):
        return []
    if provider == "ollama":
        return [str(m.get("name") or m.get("model") or "") for m in data.get("models") or [] if isinstance(m, dict)]
    return [str(m.get("id") or "") for m in data.get("data") or [] if isinstance(m, dict)]


def _one(provider: str, url: str) -> dict:
    started = time.perf_counter()
    row = {"provider": provider, "name": NAMES.get(provider, provider), "url": url,
           "base_url": url[: -len(LIST_PATH[provider])] if url.endswith(LIST_PATH[provider]) else url,
           "running": False, "models": [], "model": None, "fix": FIX_NOT_RUNNING[provider], "ms": None}
    try:
        r = httpx.get(url, timeout=TIMEOUT_S, trust_env=False)          # loopback: never through a proxy
        if r.status_code != 200:
            return row
        names = [n for n in _names(provider, r.json()) if n]
    except (httpx.HTTPError, ValueError):            # not listening, slow, or not JSON: not a usable server
        return row
    row.update(running=True, models=names, model=names[0] if names else None,
               ms=int((time.perf_counter() - started) * 1000), fix=None if names else FIX_NO_MODEL[provider])
    return row


def probe() -> list[dict]:
    """One row per fixed address: running, the models it lists, the address for a key, and the fix when needed."""
    return [_one(provider, url) for provider, url in PROBES]
