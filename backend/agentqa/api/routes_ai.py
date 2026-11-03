"""The AI endpoints: catalogue, provider keys (masked, never echoed), local detection, the routing policy, each
project's `ai:` block with its effective table, and the usage meter. Owner-only, the API envelope, the CSRF rule
and the global rate limiter apply through the app."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from agentqa.ai import budget, catalog as C, local, modes, usage
from agentqa.ai import settings as ai_settings
from agentqa.api.auth import current_user
from agentqa.api.errors import ApiError, ok
from agentqa.api.routes_projects import open_or_404
from agentqa.api.schemas_ai import KeyIn, KeyPatch, PolicyIn, ProjectAiIn
from agentqa.orchestrator import preflight

router = APIRouter(prefix="/ai", dependencies=[Depends(current_user)])
projects = APIRouter(prefix="/projects/{slug}/ai", dependencies=[Depends(current_user)])
HIDDEN = ("migrated_from", "last_mode")            # kept in project.yaml, never shown or taken from the API
CLEARABLE = ("timeout_s", "deployment", "api_version", "fallback_model")   # a PATCH null clears these; others keep
NEEDS_ADDRESS = ("azure_openai", "openai_compatible")                       # the catalogue has no usable default


def _gw():
    from agentqa.ai.router import gateway
    return gateway()


def _check_base_url(url: str | None) -> str | None:
    """http(s) only; link-local, multicast and cloud-metadata hosts refused with preflight's checker."""
    if not url:
        return None
    try:
        return preflight.check_base_url(url)
    except ValueError as exc:
        raise ApiError(422, "validation", f"base_url: {exc}") from exc


def _key_view(gw, kid: str) -> dict:
    row = next((k for k in gw.store.public_keys() if k["id"] == kid), None)
    if row is None:
        raise ApiError(404, "not_found", "No such key")
    return {**row, "scope": C.scope_of(row)}


def _find(gw, kid: str) -> dict:
    k = next((k for k in gw.store.keys() if k["id"] == kid), None)
    if k is None:
        raise ApiError(404, "not_found", "No such key")
    return k


# ---- catalogue and keys ---------------------------------------------------------------------------------

@router.get("/catalog")
def catalog():
    agents = [{"agent": a, "label": spec["label"], "tier": spec["tier"], "image": spec["image"]} for a, spec in modes.AGENTS.items()]
    return ok({"providers": C.public(), "tiers": list(C.TIER_NAMES), "agents": agents})


@router.get("/keys")
def list_keys():
    gw = _gw()
    return ok([{**k, "scope": C.scope_of(k)} for k in gw.store.public_keys()])


@router.post("/keys", status_code=201)
def add_key(body: KeyIn):
    if body.provider not in C.CATALOG:
        raise ApiError(422, "validation", f"provider: choose one of {', '.join(C.CATALOG)}")
    if not body.key and not C.CATALOG[body.provider].get("keyless"):
        raise ApiError(422, "validation", "key: this provider needs an API key")
    if body.provider in NEEDS_ADDRESS and not body.base_url:
        raise ApiError(422, "validation", "base_url: this provider has no fixed address; enter the service's URL")
    values = body.model_dump(exclude_none=True)
    values["base_url"] = _check_base_url(body.base_url) or C.CATALOG[body.provider]["base_url"]
    gw = _gw()
    kid = gw.store.upsert_key(values)
    return ok(_key_view(gw, kid), status=201)


@router.patch("/keys/{kid}")
def edit_key(kid: str, body: KeyPatch):
    gw = _gw()
    _find(gw, kid)
    values = {f: v for f, v in body.model_dump(exclude_unset=True).items() if v is not None or f in CLEARABLE}
    if "base_url" in values:                          # a null never clears the address: the key would stop working
        values["base_url"] = _check_base_url(values["base_url"])
    gw.store.upsert_key({"id": kid, **values})       # an empty key keeps the stored one (AIStore.upsert_key)
    return ok(_key_view(gw, kid))


@router.delete("/keys/{kid}")
def delete_key(kid: str):
    gw = _gw()
    _find(gw, kid)
    gw.store.delete_key(kid)
    return ok({"deleted": kid})


@router.post("/keys/{kid}/test")
async def test_key(kid: str):
    gw = _gw()
    _find(gw, kid)
    res = await run_in_threadpool(gw.test, kid)      # the detail is scrubbed of key text by the gateway
    return ok({f: res.get(f) for f in ("ok", "kind", "detail", "model", "models", "ms")})


@router.get("/local")
async def detect_local():
    return ok(await run_in_threadpool(local.probe))


# ---- policy ----------------------------------------------------------------------------------------------

@router.get("/policy")
def get_policy():
    return ok(_gw().store.policy())


@router.put("/policy")
def put_policy(body: PolicyIn):
    gw = _gw()
    values = body.model_dump(exclude_none=True)
    if "order" in values:
        unknown = [p for p in values["order"] if p not in C.CATALOG]
        if unknown:
            raise ApiError(422, "validation", f"order: unknown provider {', '.join(unknown)}")
        values["order"] += [p for p in gw.store.policy()["order"] if p not in values["order"]]
    if "cooldown_s" in values:
        values["cooldown_s"] = {**gw.store.policy()["cooldown_s"], **values["cooldown_s"]}
    gw.store.set_policy(values)
    return ok(gw.store.policy())


# ---- the project's AI block ---------------------------------------------------------------------------------

def _project_view(slug: str) -> dict:
    from agentqa.ai.client import effective
    p, s = open_or_404(slug)
    block = {k: v for k, v in (p.cfg.get("ai") or {}).items() if k not in HIDDEN}
    st = budget.status(s, ai_settings.AiSettings.from_cfg(p.cfg))
    return {"settings": block, "effective": effective(p), "notice": ai_settings.migration_notice(p.cfg.get("ai") or {}),
            "budget": st}


@projects.get("")
def get_project_ai(slug: str):
    return ok(_project_view(slug))


@projects.put("")
def put_project_ai(slug: str, body: ProjectAiIn):
    p, _ = open_or_404(slug)
    kept = {k: v for k, v in (p.cfg.get("ai") or {}).items() if k == "last_mode"}      # the old dashboard's toggle memory
    try:
        ai_settings.save_ai(p.config_path, {**body.model_dump(), **kept})
    except ValueError as exc:
        raise ApiError(422, "validation", str(exc)) from exc
    return ok(_project_view(slug))                   # from a re-read of project.yaml, not the old cfg


@projects.get("/usage")
def project_usage(slug: str, month: str | None = Query(default=None, pattern=usage.MONTH_RE.pattern)):
    p, s = open_or_404(slug)
    month = month or usage.month_key()
    return ok({**usage.summary(s, month), "budget": budget.status(s, ai_settings.AiSettings.from_cfg(p.cfg), month)})
