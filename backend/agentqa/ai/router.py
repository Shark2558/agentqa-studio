"""Routing with failover: keys in scope order (local / cloud), then the policy's provider order, then priority.

On each failure the key is handled by kind (providers.classify):
  rate limit, quota          cool the key down (Retry-After or the policy's cooldown), go to the next key
  timeout, outage, no JSON   try the same key again (attempts_per_key, with backoff), then the key's next candidate
                             model, then cool the key down
  model not available        try the next candidate model (tier table, then the key's fallback), then the next key
  key rejected, billing      mark the key dead: never retried until it is edited or passes Test connection
  request refused            go to the next key without cooling this one
When every key of a provider has failed, the next provider is tried (policy.provider_fallback).
Every failure and every switch is written to the audit log with the key text scrubbed out.

The router knows nothing about projects: `scopes` says which keys may answer and in which order (hybrid mode
passes ("local", "cloud") or the reverse), `tier` picks the model for keys set to `auto`, `cloud_image` says whether
an image may leave the computer at all (off unless the project consented), and `on_usage` gets the token counts of
every billed answer, usable or not, so the caller can record cost where it belongs (the project store).
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, replace
from typing import Callable

from agentqa.ai import catalog as C
from agentqa.ai import providers as P
from agentqa.ai.store import AIStore, agentqa_home
from agentqa.util import log, warn

ALL_SCOPES = ("local", "cloud")
LOCAL_TIMEOUT_S = 600.0            # a 4B model on a 4 GB GPU writes ~8 tokens/s: a Writer chunk can take minutes (measured 3 Nov 2026)
CHARS_PER_TOKEN = 4                # for the estimate when a provider reports no usage
UsageCallback = Callable[[dict], None]


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


@dataclass(frozen=True)
class Request:
    system: str
    user: str
    task: str = ""
    max_tokens: int = 700
    image: bytes | None = None
    tier: str | None = None
    on_usage: UsageCallback | None = None
    cloud_image: bool = False      # may the image go to a cloud key? (the project's screenshot consent)


def _dead(st: dict) -> list[str]:
    """Models this key has failed on (one per tier is possible); older rows hold a single name."""
    raw = st.get("dead_model")
    if isinstance(raw, list):
        return [str(m) for m in raw]
    return [str(raw)] if raw else []


class Gateway:
    def __init__(self, store: AIStore | None = None):
        self.store = store or AIStore()
        self._tl = threading.local()          # `last` and `last_error` belong to the calling thread (parallel workers)

    @property
    def last(self) -> dict:
        return getattr(self._tl, "last", {})

    @last.setter
    def last(self, value: dict) -> None:
        self._tl.last = value

    @property
    def last_error(self) -> str:
        return getattr(self._tl, "last_error", "")

    @last_error.setter
    def last_error(self, value: str) -> None:
        self._tl.last_error = value

    # ---- which keys may be used now ---------------------------------------------------------
    def _usable(self, k: dict, st: dict, now: float, ignore_cooldown: bool = False) -> bool:
        if (k.get("status") or "active") != "active":
            return False
        if not k.get("key") and not C.CATALOG.get(k["provider"], {}).get("keyless"):
            return False
        if st.get("state") in ("invalid_key", "billing", "model"):
            return False
        return ignore_cooldown or not (st.get("cooldown_until") and st["cooldown_until"] > now)

    def ordered(self, need_vision: bool = False, ignore_cooldown: bool = False,
                scopes: tuple[str, ...] | None = None) -> list[dict]:
        """Usable keys in the order they are tried: scope order first (as given), then the policy's provider order,
        then the key's priority. `scopes` None means every key; an empty tuple means none (fail closed)."""
        pol = self.store.policy()
        order = pol["order"]
        scopes = ALL_SCOPES if scopes is None else tuple(scopes)
        if not scopes:
            return []
        states = {s["key_id"]: s for s in self.store.states()}
        now = time.time()
        keys = [k for k in self.store.keys() if self._usable(k, states.get(k["id"], {}), now, ignore_cooldown)
                and C.scope_of(k) in scopes and (not need_vision or C.can_see(k))]
        keys.sort(key=lambda k: (scopes.index(C.scope_of(k)), order.index(k["provider"]) if k["provider"] in order else 99,
                                 int(k.get("priority") or 10)))
        if not pol.get("provider_fallback", True) and keys:
            keys = [k for k in keys if k["provider"] == keys[0]["provider"]]
        return keys

    def available(self, scopes: tuple[str, ...] | None = None, need_vision: bool = False) -> bool:
        return bool(self.ordered(need_vision=need_vision, scopes=scopes))

    def timeout_for(self, k: dict, pol: dict) -> float:
        """The key's own timeout; without one, local keys get LOCAL_TIMEOUT_S and cloud keys the policy's value."""
        if k.get("timeout_s"):
            return float(k["timeout_s"])
        return LOCAL_TIMEOUT_S if C.is_local(k) else float(pol.get("timeout_s", 60))

    # ---- one request, with failover -------------------------------------------------------------
    def complete_json(self, system: str, user: str, *, task: str = "", max_tokens: int = 700,
                      image: bytes | None = None, need_vision: bool = False, scopes: tuple[str, ...] = ("cloud",),
                      tier: str | None = None, on_usage: UsageCallback | None = None,
                      cloud_image: bool = False) -> dict | None:
        """One JSON answer from the first key that works, or None. An optional image goes only to keys that can see,
        and to a cloud key only with `cloud_image`; with `need_vision` a key that cannot take the image is not tried."""
        pol = self.store.policy()
        req = Request(system, user, task, max_tokens, image, tier, on_usage, cloud_image)
        if need_vision and not cloud_image:
            scopes = tuple(s for s in scopes if s != "cloud")      # the image must not leave the computer
        keys = self.ordered(need_vision=need_vision or image is not None, scopes=scopes)
        if not keys and image is not None and not need_vision:
            keys = self.ordered(scopes=scopes)                  # text-only keys: the image is left out
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
            out, why = self._try_key(k, pol, req)
            if out is not None:
                return out
            reasons.append(f"{k.get('label') or k['provider']}: {P.KINDS.get(why, why)}")
        self.last_error = "; ".join(reasons)
        self.store.event(None, "all_failed", self.last_error, task=task)
        warn(f"[ai] every configured AI key failed ({self.last_error}); continuing without a model")
        return None

    def _candidates(self, a: P.Adapter, k: dict, st: dict, tier: str | None) -> list[str]:
        """Models to try for this key, in order: a pinned model, else the tier table / the provider's pick, then the
        key's fallback model; never a model this key has already failed on."""
        names = st.get("models") or []
        if not names and (k.get("model") or "auto") == "auto":
            names = a.models()
            self.store.update_state(k["id"], models=names[:200])
        dead = _dead(st)
        return [m for m in C.models_for_tier(k, names, tier) if m not in dead]

    def _prepare(self, k: dict, pol: dict, req: Request) -> Request:
        """Redact for cloud keys (nothing to mask when nothing leaves the PC); drop the image for a key that cannot
        see, and for a cloud key when the project has not allowed images to leave the computer."""
        out = req
        cloud = C.scope_of(k) == "cloud"
        if cloud and pol.get("redact", True):
            out = replace(out, system=redact(req.system), user=redact(req.user))
        if req.image is not None and (not C.can_see(k) or (cloud and not req.cloud_image)):
            out = replace(out, image=None)
        return out

    def _try_key(self, k: dict, pol: dict, req: Request) -> tuple[dict | None, str]:
        a = P.adapter(k, self.timeout_for(k, pol))
        st = self.store.state(k["id"])
        kind, err = "unavailable", None
        try:
            models = self._candidates(a, k, st, req.tier)
        except P.ProviderError as exc:
            models, err, kind = [], exc, exc.kind
        if not models and err is None:
            kind, err = "model", P.ProviderError("model", "no model chosen and none listed for this key")
        prepared = self._prepare(k, pol, req)
        for model in models:
            data, kind, err = self._attempts(a, k, pol, model, prepared)
            if data is not None:
                return data, "ok"
            if kind == "model":
                self.store.update_state(k["id"], dead_model=json.dumps(_dead(st) + [model]))
                continue                        # the next candidate model
            if kind in P.RETRY_SAME:
                continue                        # a slow or broken model: the next candidate before cooling the key down
            break
        self._consequences(k, pol, kind, err, pinned=(k.get("model") or "auto") != "auto")
        return None, kind

    def _attempts(self, a: P.Adapter, k: dict, pol: dict, model: str, req: Request) -> tuple[dict | None, str, P.ProviderError | None]:
        """attempts_per_key tries of one model on one key: (answer, "ok", None) or (None, kind, error)."""
        tries = max(1, int(pol.get("attempts_per_key", 2)))
        kind, err = "unavailable", None
        for attempt in range(tries):
            started = time.time()
            try:
                text = a.chat(model, req.system, req.user, req.max_tokens, req.image)
                data = P.parse_json(text)
                if data is None:
                    raise P.ProviderError("bad_output", f"answer was not JSON: {text[:160]}")
                self._success(a, k, model, req, int((time.time() - started) * 1000))
                return data, "ok", None
            except P.ProviderError as exc:
                err, kind = exc, exc.kind
                if a.last_usage:                # the provider answered and billed us, even though the answer is unusable
                    self._report_usage(a, k, model, req, int((time.time() - started) * 1000), ok=False)
                self.store.update_state(k["id"], failures="+1", requests="+1", last_kind=kind,
                                        last_error=self.store.scrub(str(exc)),
                                        consecutive=int(self.store.state(k["id"]).get("consecutive") or 0) + 1,
                                        **({"rate_limits": "+1"} if kind in P.COOL else {}))
                self.store.event(k, kind, str(exc), task=req.task, model=model, status=exc.status)
                if kind in P.RETRY_SAME and attempt + 1 < tries:
                    time.sleep(float(pol.get("backoff_s", 1.0)) * (2 ** attempt))
                    continue
                break
        return None, kind, err

    def _success(self, a: P.Adapter, k: dict, model: str, req: Request, ms: int) -> None:
        self.store.update_state(k["id"], state="ok", consecutive=0, cooldown_until=None,
                                last_ok=time.strftime("%Y-%m-%dT%H:%M:%S"), last_ms=ms, requests="+1")
        self.store.event(k, "ok", _answered(req.task, a.last_usage), task=req.task, model=model, ms=ms)
        self.last = {"provider": k["provider"], "label": k.get("label"), "model": model, "ms": ms, "scope": C.scope_of(k)}
        self._report_usage(a, k, model, req, ms, ok=True)

    def _report_usage(self, a: P.Adapter, k: dict, model: str, req: Request, ms: int, ok: bool) -> None:
        """Tell the caller what this call cost: the provider's token counts, or (usage_known False) the sizes it can
        estimate from — the prompt length and max_tokens — so a cloud call is never counted as free."""
        if req.on_usage is None:
            return
        usage = a.last_usage or {}
        try:
            req.on_usage({"provider": k["provider"], "label": k.get("label"), "key_id": k["id"], "model": model,
                          "scope": C.scope_of(k), "tier": req.tier, "task": req.task, "ms": ms, "ok": ok,
                          "usage_known": bool(a.last_usage),
                          "input_tokens": int(usage.get("input_tokens") or 0),
                          "output_tokens": int(usage.get("output_tokens") or 0),
                          "approx_input_tokens": (len(req.system) + len(req.user)) // CHARS_PER_TOKEN + 1,
                          "max_tokens": req.max_tokens})
        except Exception as exc:  # noqa: BLE001 - a broken cost record must never lose the answer
            warn(f"[ai] the usage record failed ({exc.__class__.__name__}: {exc}); the answer is kept")

    def _consequences(self, k: dict, pol: dict, kind: str, err: P.ProviderError | None, pinned: bool) -> None:
        if kind in P.DEAD:
            self.store.update_state(k["id"], state=kind)
        elif kind == "model":
            if pinned:                          # an auto key keeps working for the tiers whose models exist
                self.store.update_state(k["id"], state="model")
        elif kind in P.COOL or kind in P.RETRY_SAME:
            secs = (err.retry_after if err and err.retry_after else None) or float(pol["cooldown_s"].get(kind, 60))
            self.store.update_state(k["id"], state="cooling", cooldown_until=time.time() + secs)

    # ---- Test connection --------------------------------------------------------------------------
    def test(self, kid: str) -> dict:
        k = next((k for k in self.store.keys() if k["id"] == kid), None)
        if not k:
            return {"ok": False, "detail": "no such key"}
        res = P.test_key(k, timeout=self.timeout_for(k, self.store.policy()))
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
