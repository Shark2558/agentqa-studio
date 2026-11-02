"""Optional AI model: the AI provider gateway (agentqa.ai), or the older per-project Ollama / Gemini settings.

Every caller must work when the model is off or fails: the model is an assistant, never a
dependency. Gemini is opt-in (llm.provider: gemini) and its key lives in the encrypted test data
vault (or the GOOGLE_API_KEY environment variable). Before anything is sent to Google, mobile
numbers, emails and other long digit runs are masked unless llm.redact is false.
"""
from __future__ import annotations

import json
import os
import re
import time

import httpx

from agentqa.util import log, warn


class LocalLLM:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get("enabled"))
        self.base = str(self.cfg.get("base_url", "http://127.0.0.1:11434")).rstrip("/")
        self.model = self.cfg.get("model", "qwen3:4b")
        self.timeout = float(self.cfg.get("timeout_s", 240))
        self._ok: bool | None = None

    def available(self) -> bool:
        if not self.enabled:
            return False
        if self._ok is None:
            try:
                r = httpx.get(f"{self.base}/api/tags", timeout=5)
                names = [m.get("name", "") for m in r.json().get("models", [])]
                self._ok = r.status_code == 200 and any(
                    n == self.model or n.split(":")[0] == self.model.split(":")[0] for n in names)
                if not self._ok:
                    warn(f"Ollama is running but model '{self.model}' is not pulled. "
                         f"Run: ollama pull {self.model}")
            except Exception as exc:  # noqa: BLE001
                warn(f"Local model not reachable at {self.base} ({exc.__class__.__name__}); "
                     f"continuing without it.")
                self._ok = False
        return self._ok

    def chat_json(self, system: str, user: str, max_tokens: int = 700) -> dict | None:
        """Ask for a JSON object. Returns None on any failure."""
        if not self.available():
            return None
        body = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": 0, "num_ctx": int(self.cfg.get("num_ctx", 8192)),
                        "num_predict": max_tokens},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        started = time.time()
        try:
            r = httpx.post(f"{self.base}/api/chat", json=body, timeout=self.timeout)
            if r.status_code == 400 and "think" in r.text:
                body.pop("think")  # older Ollama builds
                r = httpx.post(f"{self.base}/api/chat", json=body, timeout=self.timeout)
            r.raise_for_status()
            content = r.json().get("message", {}).get("content", "")
        except Exception as exc:  # noqa: BLE001
            warn(f"Local model call failed: {exc}")
            return None
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", content, flags=re.S)
            if not m:
                return None
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        log(f"    model answered in {time.time() - started:.0f}s")
        return data if isinstance(data, dict) else None


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
_SKIP_MODEL = re.compile(r"(lite|tts|image|live|audio|embed|vision|aqa|imagen|veo|transcribe|omni|nano|banana|learnlm|gemma|"
                         r"thinking|exp|computer|robotics)", re.I)


from agentqa.ai.router import redact  # noqa: E402  (kept here for older imports)


class GeminiLLM:
    """Google Gemini through its REST API (generateContent), JSON answers only."""

    def __init__(self, cfg: dict, key: str | None):
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get("enabled")) and bool(key)
        self.key = key or ""
        self.base = str(self.cfg.get("gemini_url") or GEMINI_URL).rstrip("/")
        self.model = str(self.cfg.get("gemini_model") or "auto")
        self.timeout = float(self.cfg.get("timeout_s", 120))
        self._ok: bool | None = None

    def _headers(self) -> dict:
        return {"x-goog-api-key": self.key, "Content-Type": "application/json"}

    def models(self) -> list[str]:
        r = httpx.get(f"{self.base}/models", headers=self._headers(), params={"pageSize": 200}, timeout=20)
        r.raise_for_status()
        return [m["name"].split("/", 1)[-1] for m in r.json().get("models", [])
                if "generateContent" in (m.get("supportedGenerationMethods") or [])]

    def _pick(self, names: list[str]) -> str | None:
        def ver(n):
            m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
            return float(m.group(1)) if m else 0.0
        flash = [n for n in names if "flash" in n and not _SKIP_MODEL.search(n) and "preview" not in n]
        flash = flash or [n for n in names if "flash" in n and not _SKIP_MODEL.search(n)]
        pool = flash or [n for n in names if n.startswith("gemini") and not _SKIP_MODEL.search(n)]
        return max(pool, key=lambda n: (ver(n), -len(n))) if pool else None

    def available(self) -> bool:
        if not self.enabled:
            return False
        if self._ok is None:
            try:
                if self.model == "auto":
                    picked = self._pick(self.models())
                    if not picked:
                        raise RuntimeError("no Gemini text model is available to this key")
                    self.model = picked
                    log(f"    Gemini model: {self.model}")
                self._ok = True
            except Exception as exc:  # noqa: BLE001
                warn(f"Gemini is not reachable ({str(exc)[:160]}); continuing without a model.")
                self._ok = False
        return self._ok

    def chat_json(self, system: str, user: str, max_tokens: int = 700, image_jpeg: bytes | None = None) -> dict | None:
        if not self.available():
            return None
        if self.cfg.get("redact", True):
            system, user = redact(system), redact(user)
        parts: list[dict] = [{"text": user}]
        if image_jpeg is not None and self.cfg.get("send_screenshots", False):
            import base64
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image_jpeg).decode()}})
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens, "responseMimeType": "application/json"}}
        started = time.time()
        for attempt in range(3):
            try:
                r = httpx.post(f"{self.base}/models/{self.model}:generateContent", headers=self._headers(), json=body,
                               timeout=self.timeout)
                if r.status_code in (429, 500, 503) and attempt < 2:
                    time.sleep(4 * (attempt + 1))      # free tier rate limit: wait and try again
                    continue
                r.raise_for_status()
                cands = r.json().get("candidates") or []
                text = "".join(p.get("text", "") for p in ((cands[0].get("content") or {}).get("parts") or [])) if cands else ""
                break
            except Exception as exc:  # noqa: BLE001
                warn(f"Gemini call failed: {str(exc)[:200]}")
                return None
        else:
            return None
        log(f"    Gemini answered in {time.time() - started:.0f}s")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"[\[{].*[\]}]", text, flags=re.S)
            try:
                data = json.loads(m.group(0)) if m else None
            except json.JSONDecodeError:
                data = None
        if isinstance(data, list):
            data = {"items": data}
        return data if isinstance(data, dict) else None


class GatewayLLM:
    """The AI provider gateway behind the old client interface (available, chat_json, model)."""

    def __init__(self, gw, task: str = ""):
        self.gw, self.task, self.enabled = gw, task, True

    @property
    def model(self) -> str:
        last = self.gw.last
        return f"{last.get('label')} / {last.get('model')}" if last else "AI gateway"

    def available(self) -> bool:
        return self.gw.available()

    def chat_json(self, system: str, user: str, max_tokens: int = 700, image_jpeg: bytes | None = None) -> dict | None:
        return self.gw.complete_json(system, user, task=self.task, max_tokens=max_tokens, image=image_jpeg)


def get_llm(project, task: str = ""):
    """The model client for a project, or None when the model is off.

    With keys on the AI providers page, every call goes through the gateway (failover across keys and
    providers). Without them, the older per-project settings still work: Ollama, or Gemini with its key on
    the project's Test data page."""
    cfg = project.cfg.get("llm") or {}
    if not cfg.get("enabled"):
        return None
    try:
        from agentqa.ai import gateway
        gw = gateway()
        if gw.has_keys():
            return GatewayLLM(gw, task)
    except Exception as exc:  # noqa: BLE001
        warn(f"[ai] the AI provider settings could not be read ({exc}); using the project's own model settings")
    if str(cfg.get("provider", "ollama")).lower() == "gemini":
        key = os.environ.get("GOOGLE_API_KEY")
        try:
            key = key or project.vault.secret(cfg.get("api_key_secret") or "GOOGLE_API_KEY")
        except Exception:  # noqa: BLE001
            pass
        return GeminiLLM(cfg, key)
    return LocalLLM(cfg)


def check(cfg: dict, project=None) -> str:
    try:
        from agentqa.ai import gateway
        gw = gateway()
        if gw.has_keys():
            lines = []
            for k in gw.store.keys():
                if k.get("status", "active") != "active":
                    lines.append(f"{k.get('label')} ({k['provider']}): disabled")
                    continue
                res = gw.test(k["id"])
                lines.append(f"{k.get('label')} ({k['provider']}): {'OK' if res['ok'] else 'FAILED'} - {res['detail']}")
            return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"AI provider settings could not be read: {exc}"
    if project is not None and str(cfg.get("provider", "ollama")).lower() == "gemini":
        llm = get_llm(type("P", (), {"cfg": {"llm": {**cfg, "enabled": True}}, "vault": project.vault})())
        if not llm or not llm.key:
            return "No Google API key. Add keys on the AI providers page, or GOOGLE_API_KEY on the Test data page."
        if not llm.available():
            return "Gemini is not reachable with this key (see the message above)."
        started = time.time()
        out = llm.chat_json("Reply with JSON only.", 'Return {"ok": true, "model_says": "<one short word>"}', 50)
        return (f"Gemini '{llm.model}' OK in {time.time() - started:.1f}s: {out}" if out
                else f"Gemini '{llm.model}' answered but not with JSON")
    llm = LocalLLM({**cfg, "enabled": True})
    if not llm.available():
        return (f"Local model not ready. Install Ollama from https://ollama.com, then run "
                f"'ollama pull {llm.model}', or add a provider key on the AI providers page.")
    started = time.time()
    out = llm.chat_json("Reply with JSON only.", 'Return {"ok": true, "model_says": "<one short word>"}', 30)
    if out is None:
        return "Ollama answered but did not return valid JSON; try another model."
    return f"Local model '{llm.model}' OK in {time.time() - started:.1f}s: {out}"
