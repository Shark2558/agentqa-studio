"""Provider adapters: one JSON chat call, a model list and an error classifier per API family.

Families: OpenAI chat completions (OpenAI, DeepSeek, Groq, Mistral, OpenRouter and any OpenAI-compatible
service), Azure OpenAI, Anthropic Messages, Google Gemini generateContent, and Ollama. Adding a provider
that speaks one of these families is one entry in CATALOG; a new family is one adapter class.
"""
from __future__ import annotations

import base64
import json
import re
import time
from typing import Callable, TypeVar

import anthropic
import httpx

T = TypeVar("T")

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
               "prefer": [r"qwen3", r"qwen2\.5", r"llama3"], "vision": False, "keyless": True},
}

# failure kinds and what the router does with them
RETRY_SAME = {"timeout", "connection", "unavailable", "bad_output"}    # retry this key a little, then cool it down
COOL = {"rate_limit", "quota"}                                           # cool this key down, use the next one
DEAD = {"invalid_key", "billing"}                                        # never retry until the key is edited or re-tested
KINDS = {
    "ok": "Worked", "rate_limit": "Rate limit", "quota": "Quota used up (cooling down)", "billing": "Billing or credit exhausted",
    "invalid_key": "Key rejected", "model": "Model not available", "timeout": "Timed out", "connection": "Cannot connect",
    "unavailable": "Service unavailable", "bad_request": "Request refused", "bad_output": "Answer was not JSON",
}


class ProviderError(Exception):
    def __init__(self, kind: str, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.kind, self.status, self.retry_after = kind, status, retry_after


def classify(status: int | None, text: str) -> str:
    t = (text or "").lower()
    if status == 429:
        if re.search(r"insufficient_quota|billing|credit balance|payment|plan and billing", t):
            return "billing"
        if re.search(r"quota|per day|daily|resource_exhausted.*quota|exceeded your current", t):
            return "quota"
        return "rate_limit"
    if status in (401,):
        return "invalid_key"
    if status == 403:
        return "billing" if re.search(r"billing|credit|payment", t) else "invalid_key"
    if status == 402:
        return "billing"
    if status in (400, 404, 422) and re.search(r"model", t) and re.search(
            r"not found|does not exist|not supported|decommissioned|invalid model|unknown model|no such model|not available"
            r"|deprecated|is not a valid model", t):
        return "model"
    if status == 404:
        return "model" if "model" in t else "bad_request"
    if status in (400, 413, 422):
        return "bad_request"
    if status in (408, 500, 502, 503, 504, 520, 522, 524, 529):
        return "unavailable"
    return "unavailable" if (status or 0) >= 500 else "bad_request"


def _retry_after(r) -> float | None:
    """Seconds from a Retry-After header; works for httpx and SDK responses alike (both expose .headers)."""
    v = r.headers.get("retry-after")
    try:
        return float(v) if v else None
    except ValueError:
        return None


def parse_json(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"[\[{].*[\]}]", text or "", flags=re.S)
        try:
            data = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            data = None
    if isinstance(data, list):
        data = {"items": data}
    return data if isinstance(data, dict) else None


class Adapter:
    family = ""

    def __init__(self, key: dict, timeout: float):
        self.k = key
        self.base = (key.get("base_url") or CATALOG.get(key["provider"], {}).get("base_url") or "").rstrip("/")
        self.secret = key.get("key") or ""
        self.timeout = timeout
        self.last_usage: dict | None = None     # {"input_tokens", "output_tokens"} of the last chat, when the provider reports it

    # -- to implement ------------------------------------------------------------------------
    def models(self) -> list[str]:
        raise NotImplementedError

    def chat(self, model: str, system: str, user: str, max_tokens: int, image: bytes | None) -> str:
        raise NotImplementedError

    # -- shared ------------------------------------------------------------------------------
    def _send(self, method: str, url: str, **kw) -> httpx.Response:
        try:
            r = httpx.request(method, url, timeout=kw.pop("timeout", self.timeout), **kw)
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", f"no answer within {self.timeout:.0f} s") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("connection", f"{exc.__class__.__name__}: {exc}") from exc
        if r.status_code >= 400:
            body = r.text[:600]
            raise ProviderError(classify(r.status_code, body), f"HTTP {r.status_code}: {body}", r.status_code, _retry_after(r))
        return r

    def pick(self, names: list[str]) -> str | None:
        for pat in CATALOG.get(self.k["provider"], {}).get("prefer", []):
            hits = sorted(n for n in names if re.search(pat, n))
            if hits:
                return hits[0]
        return names[0] if names else None


class OpenAIAdapter(Adapter):
    family = "openai"

    def _h(self) -> dict:
        h = {"Authorization": f"Bearer {self.secret}", "Content-Type": "application/json"}
        if self.k["provider"] == "openrouter":
            h.update({"HTTP-Referer": "https://agentqa.local", "X-Title": "AgentQA Studio"})
        return h

    def models(self) -> list[str]:
        r = self._send("GET", f"{self.base}/models", headers=self._h(), timeout=20)
        return sorted(m.get("id", "") for m in (r.json().get("data") or []) if m.get("id"))

    def _url(self, model: str) -> str:
        return f"{self.base}/chat/completions"

    def _body(self, model, system, user, max_tokens, image, json_mode=True) -> dict:
        content = user if image is None else [
            {"type": "text", "text": user},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(image).decode()}}]
        body = {"model": model, "temperature": 0, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    def chat(self, model, system, user, max_tokens, image) -> str:
        try:
            r = self._send("POST", self._url(model), headers=self._h(), json=self._body(model, system, user, max_tokens, image))
        except ProviderError as exc:
            if exc.kind == "bad_request" and "response_format" in str(exc):
                r = self._send("POST", self._url(model), headers=self._h(),
                               json=self._body(model, system, user, max_tokens, image, json_mode=False))
            else:
                raise
        ch = (r.json().get("choices") or [{}])[0]
        return ((ch.get("message") or {}).get("content")) or ""


class AzureAdapter(OpenAIAdapter):
    family = "azure"

    def _h(self) -> dict:
        return {"api-key": self.secret, "Content-Type": "application/json"}

    def _url(self, model: str) -> str:
        dep = self.k.get("deployment") or model
        ver = self.k.get("api_version") or "2024-10-21"
        return f"{self.base}/openai/deployments/{dep}/chat/completions?api-version={ver}"

    def models(self) -> list[str]:
        return [self.k.get("deployment") or self.k.get("model") or ""]


class AnthropicAdapter(Adapter):
    """Claude through the official SDK. The router owns retries, cool-downs and failover, so the client never retries.

    Current Messages API rules: no sampling parameters (current models reject them), thinking is adaptive and shares
    max_tokens (so a floor keeps short JSON tasks from being eaten by thinking), effort kept low for these small
    tasks, and the server-side refusal fallback on. A model that rejects one of the newer fields (a 400 naming the
    field, or "... not supported for this model") is asked once more in plain form, the way the OpenAI adapter drops
    response_format. Whatever the SDK raises becomes a ProviderError, so the router can fail over."""
    family = "anthropic"
    MIN_TOKENS = 1024
    EFFORT = "low"
    NEWER_FIELDS = ("output_config", "fallbacks", "anthropic-beta", "server-side-fallback")
    FALLBACK_BETA = "server-side-fallback-2026-07-01"
    MODELS_PAGE = 100

    def client(self) -> anthropic.Anthropic:
        base = re.sub(r"/v1/?$", "", self.base)              # keys store .../v1; the SDK adds /v1 itself
        return anthropic.Anthropic(api_key=self.secret, base_url=base, timeout=self.timeout, max_retries=0)

    def _call(self, fn: Callable[[], T]) -> T:
        """Run one SDK call, translating its exceptions into the gateway's ProviderError kinds."""
        try:
            return fn()
        except anthropic.APITimeoutError as exc:                  # a subclass of APIConnectionError: keep it first
            raise ProviderError("timeout", f"no answer within {self.timeout:.0f} s") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("connection", f"{exc.__class__.__name__}: {exc}") from exc
        except anthropic.APIStatusError as exc:
            body = (exc.response.text if exc.response is not None else str(exc))[:600]
            retry_after = _retry_after(exc.response) if exc.response is not None else None
            raise ProviderError(classify(exc.status_code, body), f"HTTP {exc.status_code}: {body}", exc.status_code,
                                retry_after) from exc
        except anthropic.APIError as exc:                         # anything else the SDK could not make sense of
            raise ProviderError("unavailable", f"{exc.__class__.__name__}: {str(exc)[:300]}") from exc

    def models(self) -> list[str]:
        with self.client() as c:
            return [m.id for m in self._call(lambda: list(c.models.list(limit=self.MODELS_PAGE))) if m.id]

    def _rejects_newer_fields(self, exc: ProviderError) -> bool:
        return exc.status == 400 and any(f in str(exc) for f in self.NEWER_FIELDS)

    def _request(self, c: anthropic.Anthropic, params: dict):
        """The beta call with the newer fields; plain form once if this model rejects them."""
        try:
            return self._call(lambda: c.beta.messages.create(**params, output_config={"effort": self.EFFORT},
                                                             fallbacks="default", betas=[self.FALLBACK_BETA]))
        except ProviderError as exc:
            if not self._rejects_newer_fields(exc):
                raise
            return self._call(lambda: c.messages.create(**params))

    def chat(self, model: str, system: str, user: str, max_tokens: int, image: bytes | None) -> str:
        self.last_usage = None
        content: list[dict] = [{"type": "text", "text": user + "\n\nReply with one JSON object only."}]
        if image is not None:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                        "data": base64.b64encode(image).decode()}})
        params = {"model": model, "max_tokens": max(max_tokens, self.MIN_TOKENS), "system": system,
                  "messages": [{"role": "user", "content": content}]}
        with self.client() as c:
            msg = self._request(c, params)
        if not isinstance(getattr(msg, "content", None), list):
            raise ProviderError("bad_output", f"answer was not a Messages response: {str(msg)[:160]}")
        stop = getattr(msg, "stop_reason", None)
        if stop == "refusal":
            category = getattr(getattr(msg, "stop_details", None), "category", None)
            raise ProviderError("bad_request", f"the model declined this request (refusal, category {category})")
        if stop == "max_tokens":
            raise ProviderError("bad_output", f"answer cut off at max_tokens={params['max_tokens']} "
                                              "(adaptive thinking shares that budget)")
        usage = getattr(msg, "usage", None)
        if usage is not None:
            self.last_usage = {"input_tokens": getattr(usage, "input_tokens", 0) or 0,
                               "output_tokens": getattr(usage, "output_tokens", 0) or 0}
        return "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")


_SKIP_GEMINI = re.compile(r"(lite|tts|image|live|audio|embed|vision|aqa|imagen|veo|transcribe|omni|nano|banana|learnlm|gemma|"
                          r"thinking|exp|computer|robotics)", re.I)


class GeminiAdapter(Adapter):
    family = "gemini"

    def _h(self) -> dict:
        return {"x-goog-api-key": self.secret, "Content-Type": "application/json"}

    def models(self) -> list[str]:
        r = self._send("GET", f"{self.base}/models", headers=self._h(), params={"pageSize": 200}, timeout=20)
        return [m["name"].split("/", 1)[-1] for m in r.json().get("models", [])
                if "generateContent" in (m.get("supportedGenerationMethods") or [])]

    def pick(self, names: list[str]) -> str | None:
        def ver(n):
            m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
            return float(m.group(1)) if m else 0.0
        flash = [n for n in names if "flash" in n and not _SKIP_GEMINI.search(n) and "preview" not in n]
        flash = flash or [n for n in names if "flash" in n and not _SKIP_GEMINI.search(n)]
        pool = flash or [n for n in names if n.startswith("gemini") and not _SKIP_GEMINI.search(n)]
        return max(pool, key=lambda n: (ver(n), -len(n))) if pool else None

    def chat(self, model, system, user, max_tokens, image) -> str:
        parts: list[dict] = [{"text": user}]
        if image is not None:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image).decode()}})
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens, "responseMimeType": "application/json"}}
        r = self._send("POST", f"{self.base}/models/{model}:generateContent", headers=self._h(), json=body)
        cands = r.json().get("candidates") or []
        return "".join(p.get("text", "") for p in ((cands[0].get("content") or {}).get("parts") or [])) if cands else ""


class OllamaAdapter(Adapter):
    family = "ollama"

    def models(self) -> list[str]:
        r = self._send("GET", f"{self.base}/api/tags", timeout=5)
        return [m.get("name", "") for m in r.json().get("models", [])]

    def chat(self, model, system, user, max_tokens, image) -> str:
        msg = {"role": "user", "content": user}
        if image is not None:
            msg["images"] = [base64.b64encode(image).decode()]
        r = self._send("POST", f"{self.base}/api/chat", json={
            "model": model, "stream": False, "format": "json", "think": False,
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": max_tokens},
            "messages": [{"role": "system", "content": system}, msg]})
        return (r.json().get("message") or {}).get("content", "")


FAMILIES = {"openai": OpenAIAdapter, "azure": AzureAdapter, "anthropic": AnthropicAdapter, "gemini": GeminiAdapter,
            "ollama": OllamaAdapter}


def adapter(key: dict, timeout: float = 60) -> Adapter:
    fam = CATALOG.get(key["provider"], {}).get("family", "openai")
    return FAMILIES[fam](key, timeout)


def test_key(key: dict, timeout: float = 30) -> dict:
    """Test connection: list the models, then ask for a tiny JSON answer. Never raises."""
    a = adapter(key, timeout)
    out = {"ok": False, "models": [], "model": None, "kind": None, "detail": "", "ms": None}
    try:
        out["models"] = a.models()[:200]
    except ProviderError as exc:
        if exc.kind in DEAD or exc.kind in COOL:
            out.update(kind=exc.kind, detail=str(exc)[:300])
            return out
    model = key.get("model") or "auto"
    if model == "auto":
        model = a.pick(out["models"])
        if not model:
            out.update(kind="model", detail="No model listed for this key: choose one")
            return out
    notes = []
    for m in [model] + ([key["fallback_model"]] if key.get("fallback_model") and key["fallback_model"] != model else []):
        out["model"] = m
        started = time.time()
        try:
            text = a.chat(m, "Reply with JSON only.", 'Return {"ok": true}', 30, None)
            out["ms"] = int((time.time() - started) * 1000)
            if parse_json(text) is None:
                out.update(kind="bad_output", detail=f"answered, but not with JSON: {text[:120]}")
            else:
                out.update(ok=True, kind="ok", detail="; ".join(notes + [f"{m} answered in {out['ms']} ms"]))
            return out
        except ProviderError as exc:
            out.update(kind=exc.kind, detail=str(exc)[:300])
            if exc.kind != "model":
                return out
            notes.append(f"model {m} is not available, so the fallback model is used")
    return out
