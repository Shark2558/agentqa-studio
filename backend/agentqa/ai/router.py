"""Routing with failover: keys in priority order within a provider, providers in the policy's order.

On each failure the key is handled by kind (providers.classify):
  rate limit, quota          cool the key down (Retry-After or the policy's cooldown), go to the next key
  timeout, outage, no JSON   try the same key again (attempts_per_key, with backoff), then cool it down
  model not available        try the key's fallback model, then the next key
  key rejected, billing      mark the key dead: never retried until it is edited or passes Test connection
  request refused            go to the next key without cooling this one
When every key of a provider has failed, the next provider is tried (policy.provider_fallback).
Every failure and every switch is written to the audit log with the key text scrubbed out.
"""
from __future__ import annotations

import re
import threading
import time

from agentqa.ai import providers as P
from agentqa.ai.store import AIStore, agentqa_home
from agentqa.util import log, warn


def redact(text: str) -> str:
    """Mask personal data before text leaves the computer."""
    text = re.sub(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", "<email>", text)
    text = re.sub(r"(?<!\d)(\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)", "<mobile>", text)
    text = re.sub(r"(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)", "<12-digit number>", text)
    return text


def _answered(task: str, usage: dict | None) -> str:
    """Audit-log line for a successful answer, with the token counts when the provider reported them."""
    line = f"{task or 'request'} answered"
    if usage:
        line += f" · {usage.get('input_tokens', 0)} in / {usage.get('output_tokens', 0)} out tokens"
    return line


class Gateway:
    def __init__(self, store: AIStore | None = None):
        self.store = store or AIStore()
        self.last: dict = {}
        self.last_error: str = ""

    # ---- which keys may be used now ---------------------------------------------------------
    def _usable(self, k: dict, st: dict, now: float, ignore_cooldown: bool = False) -> bool:
        if k.get("status", "active") != "active":
            return False
        if not k.get("key") and not P.CATALOG.get(k["provider"], {}).get("keyless"):
            return False
        if st.get("state") in ("invalid_key", "billing", "model"):
            return False
        return ignore_cooldown or not (st.get("cooldown_until") and st["cooldown_until"] > now)

    def ordered(self, need_vision: bool = False, ignore_cooldown: bool = False) -> list[dict]:
        pol = self.store.policy()
        order = pol["order"]
        states = {s["key_id"]: s for s in self.store.states()}
        now = time.time()
        keys = [k for k in self.store.keys() if self._usable(k, states.get(k["id"], {}), now, ignore_cooldown)
                and (not need_vision or P.CATALOG.get(k["provider"], {}).get("vision"))]
        keys.sort(key=lambda k: (order.index(k["provider"]) if k["provider"] in order else 99, int(k.get("priority", 10))))
        if not pol.get("provider_fallback", True) and keys:
            keys = [k for k in keys if k["provider"] == keys[0]["provider"]]
        return keys

    def has_keys(self) -> bool:
        return any(k.get("status", "active") == "active" for k in self.store.keys())

    def available(self) -> bool:
        return bool(self.ordered())

    # ---- one request, with failover -------------------------------------------------------------
    def complete_json(self, system: str, user: str, *, task: str = "", max_tokens: int = 700,
                      image: bytes | None = None, need_vision: bool = False) -> dict | None:
        pol = self.store.policy()
        if image is not None and not pol.get("send_screenshots"):
            image = None
        if pol.get("redact", True):
            system, user = redact(system), redact(user)
        keys = self.ordered(need_vision=need_vision or image is not None) or (self.ordered() if image is not None else [])
        if not keys:
            self.last_error = "no usable AI key (all disabled, rejected or cooling down)"
            self.store.event(None, "no_key", self.last_error, task=task)
            return None
        reasons: list[str] = []
        prev: dict | None = None
        for k in keys:
            if prev is not None:
                self.store.event(prev, "switched", f"{reasons[-1]}; trying {k['label']} ({k['provider']})", task=task,
                                 switched_to=k.get("label") or k["id"])
            prev = k
            out, why = self._try_key(k, pol, system, user, task, max_tokens, image)
            if out is not None:
                return out
            reasons.append(f"{k.get('label') or k['provider']}: {P.KINDS.get(why, why)}")
        self.last_error = "; ".join(reasons)
        self.store.event(None, "all_failed", self.last_error, task=task)
        warn(f"[ai] every configured AI key failed ({self.last_error}); continuing without a model")
        return None

    def _model_for(self, a: P.Adapter, k: dict, st: dict) -> str | None:
        m = k.get("model") or "auto"
        if m != "auto":
            return m
        names = st.get("models") or []
        if not names:
            names = a.models()
            self.store.update_state(k["id"], models=names[:200])
        return a.pick(names)

    def _try_key(self, k: dict, pol: dict, system: str, user: str, task: str, max_tokens: int,
                 image: bytes | None) -> tuple[dict | None, str]:
        a = P.adapter(k, float(pol.get("timeout_s", 60)))
        st = self.store.state(k["id"])
        kind = "unavailable"
        err: P.ProviderError | None = None
        try:
            first = self._model_for(a, k, st)
        except P.ProviderError as exc:
            first, err, kind = None, exc, exc.kind
        models = [m for m in [first, k.get("fallback_model")] if m and m != st.get("dead_model")]
        if first is None and err is None:
            kind, err = "model", P.ProviderError("model", "no model chosen and none listed for this key")
        for model in models:
            for attempt in range(max(1, int(pol.get("attempts_per_key", 2)))):
                started = time.time()
                try:
                    text = a.chat(model, system, user, max_tokens, image)
                    data = P.parse_json(text)
                    if data is None:
                        raise P.ProviderError("bad_output", f"answer was not JSON: {text[:160]}")
                    ms = int((time.time() - started) * 1000)
                    self.store.update_state(k["id"], state="ok", consecutive=0, cooldown_until=None, last_ok=time.strftime(
                        "%Y-%m-%dT%H:%M:%S"), last_ms=ms, requests="+1")
                    self.store.event(k, "ok", _answered(task, a.last_usage), task=task, model=model, ms=ms)
                    self.last = {"provider": k["provider"], "label": k.get("label"), "model": model, "ms": ms}
                    return data, "ok"
                except P.ProviderError as exc:
                    err, kind = exc, exc.kind
                    self.store.update_state(k["id"], failures="+1", requests="+1", last_kind=kind,
                                            last_error=self.store.scrub(str(exc)),
                                            consecutive=int(self.store.state(k["id"]).get("consecutive") or 0) + 1,
                                            **({"rate_limits": "+1"} if kind in P.COOL else {}))
                    self.store.event(k, kind, str(exc), task=task, model=model, status=exc.status)
                    if kind in P.RETRY_SAME and attempt + 1 < int(pol.get("attempts_per_key", 2)):
                        time.sleep(float(pol.get("backoff_s", 1.0)) * (2 ** attempt))
                        continue
                    break
            if kind == "model":
                self.store.update_state(k["id"], dead_model=model)
                continue            # the fallback model, if any
            break
        # consequences for the key
        if kind in P.DEAD:
            self.store.update_state(k["id"], state=kind)
        elif kind == "model":
            self.store.update_state(k["id"], state="model")
        elif kind in P.COOL or kind in P.RETRY_SAME:
            secs = (err.retry_after if err and err.retry_after else None) or float(pol["cooldown_s"].get(kind, 60))
            self.store.update_state(k["id"], state="cooling", cooldown_until=time.time() + secs)
        return None, kind

    # ---- Test connection --------------------------------------------------------------------------
    def test(self, kid: str) -> dict:
        k = next((k for k in self.store.keys() if k["id"] == kid), None)
        if not k:
            return {"ok": False, "detail": "no such key"}
        res = P.test_key(k, timeout=float(self.store.policy().get("timeout_s", 60)))
        res["detail"] = self.store.scrub(res.get("detail"))
        fields = {"models": res.get("models") or self.store.state(kid).get("models") or [], "last_kind": res["kind"],
                  "last_error": None if res["ok"] else res["detail"], "last_ms": res.get("ms")}
        if res["ok"]:
            fields.update(state="ok", consecutive=0, cooldown_until=None, dead_model=None,
                          last_ok=time.strftime("%Y-%m-%dT%H:%M:%S"))
        elif res["kind"] in P.DEAD or res["kind"] == "model":
            fields["state"] = res["kind"]
        self.store.update_state(kid, **fields)
        self.store.event(k, "test_ok" if res["ok"] else "test_failed", res["detail"], task="test connection",
                         model=res.get("model") or "", ms=res.get("ms"))
        log(f"  [ai] {k.get('label')} ({k['provider']}): {'OK' if res['ok'] else 'FAILED'} - {res['detail']}")
        return res


_GW: dict[str, Gateway] = {}
_GL = threading.Lock()


def gateway() -> Gateway:
    home = str(agentqa_home())
    with _GL:
        if home not in _GW:
            _GW[home] = Gateway(AIStore())
        return _GW[home]
