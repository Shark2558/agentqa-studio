"""Provider adapters: one JSON chat call and a model list per API family; `classify` (agentqa/ai/classify.py) reads
their errors.

Families: OpenAI chat completions (OpenAI, DeepSeek, Groq, Mistral, OpenRouter, LM Studio and any OpenAI-compatible
service), Azure OpenAI, Anthropic Messages, Google Gemini generateContent, and Ollama. Adding a provider
that speaks one of these families is one entry in agentqa/ai/catalog.py; a new family is one adapter class.
Every adapter fills `last_usage` ({input_tokens, output_tokens}) after a successful chat when the provider reports it.
"""
from __future__ import annotations

import base64
import json
import re
import time
from typing import Callable, TypeVar
from urllib.parse import quote, urlsplit

import anthropic
import httpx

from agentqa.ai.catalog import LOOPBACK_HOSTS

T = TypeVar("T")

from agentqa.ai.catalog import CATALOG, gemini_pick, prefer_pick  # noqa: F401  (CATALOG re-exported for older imports)
from agentqa.ai.classify import classify                            # what an HTTP error means (P.classify, as before)

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


def _retry_after(r) -> float | None:
    """Seconds from a Retry-After header; works for httpx and SDK responses alike (both expose .headers)."""
    v = r.headers.get("retry-after")
    try:
        return float(v) if v else None
    except ValueError:
        return None


MAX_ANSWER_CHARS = 400_000         # a model answer longer than this is not a JSON object we asked for


def parse_json(text: str) -> dict | None:
    """The JSON object in a model's answer (fenced or bare), or None. Model output is untrusted: a crash here must
    not escape the router, so nesting bombs and oversized answers are just \"not JSON\"."""
    text = (text or "")[:MAX_ANSWER_CHARS]
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, RecursionError):
        m = re.search(r"[\[{].*[\]}]", text, flags=re.S)
        try:
            data = json.loads(m.group(0)) if m else None
        except (json.JSONDecodeError, RecursionError):
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
        self.local_host = (urlsplit(self.base).hostname or "").lower() in LOOPBACK_HOSTS
        self.last_usage: dict | None = None     # {"input_tokens", "output_tokens"} of the last chat, when the provider reports it

    # -- to implement ------------------------------------------------------------------------
    def models(self) -> list[str]:
        raise NotImplementedError

    def chat(self, model: str, system: str, user: str, max_tokens: int, image: bytes | None) -> str:
        raise NotImplementedError

    # -- shared ------------------------------------------------------------------------------
    def _send(self, method: str, url: str, **kw) -> httpx.Response:
        """One HTTP call. A loopback address ignores proxy settings: nothing local may leave through HTTP_PROXY."""
        try:
            r = httpx.request(method, url, timeout=kw.pop("timeout", self.timeout), trust_env=not self.local_host, **kw)
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", f"no answer within {self.timeout:.0f} s") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("connection", f"{exc.__class__.__name__}: {exc}") from exc
        if r.status_code >= 400:
            body = r.text[:600]
            raise ProviderError(classify(r.status_code, body, self.k["provider"]), f"HTTP {r.status_code}: {body}",
                                r.status_code, _retry_after(r))
        return r

    def pick(self, names: list[str]) -> str | None:
        return prefer_pick(self.k["provider"], names)

    @staticmethod
    def _json(r: httpx.Response) -> dict:
        """The response body as a JSON object, or ProviderError (a proxy page or an empty body is not an answer)."""
        try:
            data = r.json()
        except ValueError as exc:
            raise ProviderError("bad_output", f"answer was not JSON: {r.text[:160]}") from exc
        if not isinstance(data, dict):
            raise ProviderError("bad_output", f"answer was not a JSON object: {str(data)[:160]}")
        return data

    def _usage(self, prompt, completion) -> None:
        """Keep the token counts of the last answer (None when the provider sent none) for the cost record."""
        self.last_usage = None if prompt is None and completion is None else {"input_tokens": int(prompt or 0),
                                                                              "output_tokens": int(completion or 0)}


class OpenAIAdapter(Adapter):
    family = "openai"

    def _h(self) -> dict:
        h = {"Authorization": f"Bearer {self.secret}", "Content-Type": "application/json"}
        if self.k["provider"] == "openrouter":
            h.update({"HTTP-Referer": "https://agentqa.local", "X-Title": "AgentQA Studio"})
        return h

    def models(self) -> list[str]:
        r = self._send("GET", f"{self.base}/models", headers=self._h(), timeout=20)
        return sorted(m.get("id", "") for m in (self._json(r).get("data") or []) if isinstance(m, dict) and m.get("id"))

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
        self.last_usage = None
        try:
            r = self._send("POST", self._url(model), headers=self._h(), json=self._body(model, system, user, max_tokens, image))
        except ProviderError as exc:
            if exc.kind == "bad_request" and "response_format" in str(exc):
                r = self._send("POST", self._url(model), headers=self._h(),
                               json=self._body(model, system, user, max_tokens, image, json_mode=False))
            else:
                raise
        data = self._json(r)
        usage = data.get("usage") or {}
        self._usage(usage.get("prompt_tokens"), usage.get("completion_tokens"))
        ch = (data.get("choices") or [{}])[0]
        return ((ch.get("message") or {}).get("content")) or ""


class AzureAdapter(OpenAIAdapter):
    family = "azure"

    def _h(self) -> dict:
        return {"api-key": self.secret, "Content-Type": "application/json"}

    def _url(self, model: str) -> str:
        dep = self.k.get("deployment") or model
        ver = self.k.get("api_version") or "2024-10-21"
        return f"{self.base}/openai/deployments/{quote(dep, safe='')}/chat/completions?api-version={quote(ver, safe='')}"

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
            raise ProviderError(classify(exc.status_code, body, self.k["provider"]), f"HTTP {exc.status_code}: {body}",
                                exc.status_code, retry_after) from exc
        except anthropic.APIError as exc:                         # anything else the SDK could not make sense of
            raise ProviderError("unavailable", f"{exc.__class__.__name__}: {str(exc)[:300]}") from exc

    def models(self) -> list[str]:
        with self.client() as c:
            return [m.id for m in self._call(lambda: list(c.models.list(limit=self.MODELS_PAGE))) if m.id]

    def _rejects_newer_fields(self, exc: ProviderError) -> bool:
        # read as a refused request or a model limit ("... not supported for this model"); never a billing answer
        return exc.kind in ("bad_request", "model") and exc.status == 400 and any(f in str(exc) for f in self.NEWER_FIELDS)

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


class GeminiAdapter(Adapter):
    family = "gemini"

    def _h(self) -> dict:
        return {"x-goog-api-key": self.secret, "Content-Type": "application/json"}

    def models(self) -> list[str]:
        r = self._send("GET", f"{self.base}/models", headers=self._h(), params={"pageSize": 200}, timeout=20)
        return [str(m.get("name", "")).split("/", 1)[-1] for m in self._json(r).get("models", []) if isinstance(m, dict)
                and "generateContent" in (m.get("supportedGenerationMethods") or [])]

    def pick(self, names: list[str]) -> str | None:
        return gemini_pick(names)                 # -latest aliases first; never by highest version (M0.3 gap a)

    def chat(self, model, system, user, max_tokens, image) -> str:
        self.last_usage = None
        parts: list[dict] = [{"text": user}]
        if image is not None:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(image).decode()}})
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens, "responseMimeType": "application/json"}}
        r = self._send("POST", f"{self.base}/models/{quote(model, safe='')}:generateContent", headers=self._h(), json=body)
        data = self._json(r)
        meta = data.get("usageMetadata") or {}
        if meta:                                 # thinking tokens are billed as output, in their own field
            self._usage(meta.get("promptTokenCount"), int(meta.get("candidatesTokenCount") or 0) + int(meta.get("thoughtsTokenCount") or 0))
        cands = data.get("candidates") or []
        return "".join(p.get("text", "") for p in ((cands[0].get("content") or {}).get("parts") or [])) if cands else ""


class OllamaAdapter(Adapter):
    family = "ollama"

    def models(self) -> list[str]:
        r = self._send("GET", f"{self.base}/api/tags", timeout=5)
        return [str(m.get("name", "")) for m in self._json(r).get("models", []) if isinstance(m, dict)]

    def _post_chat(self, body: dict) -> httpx.Response:
        """A looping model ("prediction aborted, token repeat limit reached") is a bad answer, not an outage to cool down."""
        try:
            return self._send("POST", f"{self.base}/api/chat", json=body)
        except ProviderError as exc:
            if exc.kind == "unavailable" and "prediction aborted" in str(exc):
                raise ProviderError("bad_output", f"the model looped and Ollama stopped it: {exc}") from exc
            raise

    def chat(self, model, system, user, max_tokens, image) -> str:
        self.last_usage = None
        msg = {"role": "user", "content": user}
        if image is not None:
            msg["images"] = [base64.b64encode(image).decode()]
        body = {"model": model, "stream": False, "format": "json", "think": False,
                "options": {"temperature": 0, "num_ctx": 8192, "num_predict": max_tokens},
                "messages": [{"role": "system", "content": system}, msg]}
        try:
            r = self._post_chat(body)
        except ProviderError as exc:
            if exc.kind != "bad_request" or "think" not in str(exc):
                raise
            r = self._post_chat({k: v for k, v in body.items() if k != "think"})
        data = self._json(r)
        self._usage(data.get("prompt_eval_count"), data.get("eval_count"))
        return (data.get("message") or {}).get("content", "")


FAMILIES = {"openai": OpenAIAdapter, "azure": AzureAdapter, "anthropic": AnthropicAdapter, "gemini": GeminiAdapter,
            "ollama": OllamaAdapter}


def adapter(key: dict, timeout: float = 60) -> Adapter:
    fam = CATALOG.get(key["provider"], {}).get("family", "openai")
    return FAMILIES[fam](key, timeout)


# The connection test: a question with its JSON answer in it; the toy 'Return {"ok": true}' made qwen3:4b loop (3 Nov 2026).
TEST_SYSTEM = "You check that a service answers. Reply with one JSON object and nothing else."
TEST_USER = 'Is the service reachable? Answer with the JSON object {"ok": true}.'
TEST_TOKENS = 40


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
            text = a.chat(m, TEST_SYSTEM, TEST_USER, TEST_TOKENS, None)
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
