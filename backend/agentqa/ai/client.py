"""`model_for(project, agent)`: the one door every agent uses to reach a model.

    llm = model_for(project, "casegen")        # None when the project's mode, consent, budget or keys say no AI
    if llm and llm.available():
        out = llm.chat_json(system, user, max_tokens=700, image_jpeg=None)

The client keeps the old per-project interface (available, chat_json, model, enabled) and the gateway's
(complete_json), so agents change one import. It asks the router for a scope order and a tier, never a model id;
checks the monthly budget before every cloud attempt (Cloud drops to no AI at the cap, Hybrid to local only);
withholds images the project has not consented to; and records each answer's usage in the project store.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

from agentqa import live
from agentqa.ai import budget, catalog as C, modes, usage
from agentqa.ai.settings import AiSettings
from agentqa.store import Store

if TYPE_CHECKING:                                     # the router pulls in the provider SDKs; type-only here
    from agentqa.ai.router import Gateway
    from agentqa.config import Project

log = logging.getLogger("agentqa.ai.client")
PIPELINE_ENV = "AGENTQA_PIPELINE_ID"
MAX_ANNOUNCED = 10_000
_ANNOUNCED: set[tuple[str, str, str]] = set()        # (pipeline, project root, agent): the `model` event, once per stage
_LOCK = threading.Lock()


class AiClient:
    """One agent's model client. Use it from the thread that created it (its sqlite connection is thread-bound) and
    close it, or use it as a context manager, when the stage is done."""
    enabled = True

    def __init__(self, gw: "Gateway", project: "Project", settings: AiSettings, route: modes.Route, store: Store):
        self.gw, self.project, self.settings, self.route, self.store = gw, project, settings, route, store
        self.reason: str | None = None            # set when a call was refused (the budget cap), for the caller's log
        self._last: dict = {}                     # this client's last answer: provider, label, model

    def close(self) -> None:
        try:
            self.store.close()
        except Exception:  # noqa: BLE001 - already closed
            pass

    def __enter__(self) -> "AiClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def model(self) -> str:
        if self._last:
            return f"{self._last.get('label')} / {self._last.get('model')}"
        return f"{'/'.join(self.route.scopes)} AI, {self.route.tier} tier"

    @property
    def image_allowed(self) -> bool:
        return self.route.image

    def available(self) -> bool:
        scopes = self._scopes_now()
        return bool(scopes) and self.gw.available(scopes=scopes, need_vision=self.route.need_vision)

    def _scopes_now(self) -> tuple[str, ...] | None:
        """The scopes for this call: the budget is checked before every cloud attempt, so a cap reached mid-run
        counts at once (Cloud: no AI from here on; Hybrid: local only)."""
        scopes = self.route.scopes
        if "cloud" not in scopes:
            return scopes
        st = budget.check(self.store, self.settings, project=self.project.name)
        if st["state"] != "capped":
            return scopes
        if self.settings.mode == "hybrid":
            return ("local",)
        self.reason = budget.reason(st)
        return None

    def chat_json(self, system: str, user: str, max_tokens: int = 700, image_jpeg: bytes | None = None) -> dict | None:
        return self.complete_json(system, user, max_tokens=max_tokens, image=image_jpeg)

    def complete_json(self, system: str, user: str, *, task: str = "", max_tokens: int = 700,
                      image: bytes | None = None) -> dict | None:
        scopes = self._scopes_now()
        if not scopes:
            return None
        if image is not None and not self.route.image:
            image = None                                       # no consent, or no model that can see: text only
        return self.gw.complete_json(system, user, task=task or self.route.agent, max_tokens=max_tokens, image=image,
                                     need_vision=self.route.need_vision, scopes=scopes, tier=self.route.tier,
                                     on_usage=self._on_usage, cloud_image=self.settings.send_screenshots)

    def _on_usage(self, info: dict) -> None:
        if info.get("ok"):
            self._last = {k: info.get(k) for k in ("provider", "label", "model")}
        row = usage.record(self.store, info, agent=self.route.agent, pipeline=os.environ.get(PIPELINE_ENV),
                           prices=self.gw.store.policy().get("prices"))
        _emit_cost(self.route.agent, row, ok=bool(info.get("ok")))


def _emit_cost(agent: str, row: dict, ok: bool) -> None:
    """One `cost` line per billed call for the Live View's cards (M1.3): the figures of the usage row, never the
    prompt, the answer or which key answered. A failed write loses the line, never the usage row or the answer."""
    label = modes.AGENTS[agent]["label"] if agent in modes.AGENTS else agent
    try:
        live.emit("ai", "cost", f"{label}: {row['model']} · ${row['cost_usd']:.4f}", agent_key=agent, tier=row["tier"],
                  scope=row["scope"], provider=row["provider"], model=row["model"], input_tokens=row["input_tokens"],
                  output_tokens=row["output_tokens"], cost_usd=row["cost_usd"], estimated=bool(row["estimated"]),
                  ms=row["ms"], ok=ok)
    except Exception as exc:  # noqa: BLE001 - the live view is a convenience; the usage table is the record
        log.warning("live cost line not written for %s: %s", agent, type(exc).__name__)


def _keys_at_hand(gw: "Gateway") -> dict:
    return {"have_local": gw.available(scopes=("local",)), "have_cloud": gw.available(scopes=("cloud",)),
            "local_vision": gw.available(scopes=("local",), need_vision=True)}


def _announce(project: "Project", agent: str, route: modes.Route, settings: AiSettings, model: str | None) -> None:
    key = (os.environ.get(PIPELINE_ENV, ""), str(project.root), agent)
    with _LOCK:
        if key in _ANNOUNCED:
            return
        if len(_ANNOUNCED) >= MAX_ANNOUNCED:               # a long-lived server: forget, rather than grow forever
            _ANNOUNCED.clear()
        _ANNOUNCED.add(key)
    label = modes.AGENTS[agent]["label"]
    what = f"no model ({route.reason})" if route.reason else f"{model or '/'.join(route.scopes)} ({route.tier})"
    live.emit("ai", "model", f"{label}: {what}", agent_key=agent, tier=route.tier, mode=settings.mode,
              scopes=list(route.scopes) or None, reason=route.reason)


def _first_model(gw: "Gateway", route: modes.Route) -> tuple[str | None, str | None]:
    """(provider, model) the router would ask first for this route, without calling anyone."""
    keys = gw.ordered(scopes=route.scopes, need_vision=route.need_vision) if route.enabled else []
    if not keys:
        return None, None
    k = keys[0]
    return k["provider"], C.model_for_tier(k, gw.store.state(k["id"]).get("models") or [], route.tier)


def model_for(project: "Project", agent: str) -> AiClient | None:
    """The model client for one agent of a project, or None (the reason is in the live view and `effective`)."""
    settings = AiSettings.from_cfg(project.cfg)
    if not settings.enabled():
        route = modes.resolve(settings, agent, have_local=False, have_cloud=False)
        _announce(project, agent, route, settings, None)
        return None                                           # no AI: the key store is never opened
    from agentqa.ai.router import gateway
    gw = gateway()
    store = Store(project.db_path)
    capped = settings.mode in ("cloud", "hybrid") and \
        budget.check(store, settings, project=project.name)["state"] == "capped"
    route = modes.resolve(settings, agent, capped=capped, **_keys_at_hand(gw))
    _announce(project, agent, route, settings, _first_model(gw, route)[1])
    if not route.enabled:
        store.close()
        return None
    return AiClient(gw, project, settings, route, store)


def effective(project: "Project") -> list[dict]:
    """Per agent: the tier, scopes and the provider / model that would answer first, or the reason there is none."""
    settings = AiSettings.from_cfg(project.cfg)
    if not settings.enabled():
        routes = modes.effective(settings, have_local=False, have_cloud=False)
        gw = None
    else:
        from agentqa.ai.router import gateway
        gw = gateway()
        store = Store(project.db_path)
        try:
            capped = settings.mode in ("cloud", "hybrid") and budget.status(store, settings)["state"] == "capped"
        finally:
            store.close()
        routes = modes.effective(settings, capped=capped, **_keys_at_hand(gw))
    out = []
    for r in routes:
        provider, model = _first_model(gw, r) if gw is not None else (None, None)
        out.append({"agent": r.agent, "label": modes.AGENTS[r.agent]["label"], "tier": r.tier, "scopes": list(r.scopes),
                    "image": r.image, "provider": provider, "model": model, "reason": r.reason})
    return out
