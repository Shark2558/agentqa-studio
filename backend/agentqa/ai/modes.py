"""How a project's AI mode, consent, budget and keys decide which keys may answer an agent (pure; no I/O).

| Mode   | cheap            | balanced / strong | needs an image                        | text consent off | monthly cap reached |
|--------|------------------|-------------------|---------------------------------------|------------------|---------------------|
| none   | no AI            | no AI             | no AI                                 | —                | —                   |
| local  | local keys       | local keys        | a local vision model, else text only  | not needed       | not affected (free) |
| cloud  | cloud keys       | cloud keys        | cloud, image only with consent        | no AI            | no AI + alert       |
| hybrid | local, then cloud| cloud, then local | cloud with consent, else local        | local only       | local only          |

"Local key" = a local provider on a loopback address (catalog.is_local). Every "no AI" comes with a reason in
plain English, shown in the effective table, the live view and `doctor`.
"""
from __future__ import annotations

from dataclasses import dataclass

from agentqa.ai.settings import AiSettings

# agent key -> default tier, whether it uses an image (none | optional | required), and its name on the pages
AGENTS: dict[str, dict] = {
    "req_chat": {"tier": "strong", "image": "none", "label": "Requirement Chat"},
    "req_writer": {"tier": "strong", "image": "none", "label": "Requirement Writer"},
    "srs": {"tier": "balanced", "image": "none", "label": "Requirement Analyst"},
    "requirements": {"tier": "balanced", "image": "none", "label": "Requirement enrichment"},
    "casegen": {"tier": "balanced", "image": "none", "label": "Test Case Generation"},
    "visual_qa": {"tier": "balanced", "image": "optional", "label": "Visual QA"},
    "documents": {"tier": "vision", "image": "required", "label": "Document OCR"},
    "triage": {"tier": "cheap", "image": "none", "label": "Defect title polish"},
    "assistant": {"tier": "cheap", "image": "none", "label": "Assistant"},
    "login": {"tier": "cheap", "image": "none", "label": "Login navigation"},
}
NO_LOCAL = "no local AI is set up for this computer yet: on the AI page press Use it next to the running Ollama or LM Studio"
NO_CLOUD = "no cloud AI key is enabled: add one on the AI page"
NO_TEXT_CONSENT = "you have not allowed text to be sent to a cloud provider (AI page, consent)"
NO_IMAGE_CONSENT = "you have not allowed images to be sent to a cloud provider (AI page, consent)"
NO_LOCAL_VISION = "no local model on this computer can read images"
CAPPED = "the monthly AI budget is used up: cloud AI is off until next month or a higher cap"


@dataclass(frozen=True)
class Route:
    agent: str
    tier: str
    scopes: tuple[str, ...] = ()
    image: bool = False            # may an image travel with the request?
    need_vision: bool = False      # must the answering key be able to see?
    reason: str | None = None      # set: no AI for this agent, and why

    @property
    def enabled(self) -> bool:
        return self.reason is None


def _off(agent: str, tier: str, reason: str) -> Route:
    return Route(agent, tier, reason=reason)


def _local(agent: str, tier: str, image: str, *, have_local: bool, local_vision: bool) -> Route:
    if not have_local:
        return _off(agent, tier, NO_LOCAL)
    if image == "required" and not local_vision:
        return _off(agent, tier, NO_LOCAL_VISION)
    return Route(agent, tier, ("local",), image=local_vision and image != "none", need_vision=image == "required")


def _cloud(agent: str, tier: str, image: str, s: AiSettings, *, have_cloud: bool, capped: bool) -> Route:
    if not s.send_text:
        return _off(agent, tier, NO_TEXT_CONSENT)
    if capped:
        return _off(agent, tier, CAPPED)
    if not have_cloud:
        return _off(agent, tier, NO_CLOUD)
    if image == "required" and not s.send_screenshots:
        return _off(agent, tier, NO_IMAGE_CONSENT)
    return Route(agent, tier, ("cloud",), image=s.send_screenshots and image != "none", need_vision=image == "required")


def _hybrid(agent: str, tier: str, image: str, s: AiSettings, *, have_local: bool, have_cloud: bool, capped: bool,
            local_vision: bool) -> Route:
    cloud_ok = s.send_text and not capped and have_cloud
    if not cloud_ok:
        local = _local(agent, tier, image, have_local=have_local, local_vision=local_vision)
        if local.enabled or have_local:
            return local
        why = CAPPED if capped and s.send_text else (NO_TEXT_CONSENT if not s.send_text else NO_CLOUD)
        return _off(agent, tier, f"{why}; and {NO_LOCAL}")
    scopes = ("local", "cloud") if tier == "cheap" else ("cloud", "local")
    if image == "none" or s.send_screenshots:
        return Route(agent, tier, scopes, image=image != "none", need_vision=image == "required")
    if local_vision and have_local:                               # no consent: the image goes only to this computer
        return Route(agent, tier, ("local",), image=True, need_vision=image == "required")
    if image == "required":
        return _off(agent, tier, f"{NO_IMAGE_CONSENT}, and {NO_LOCAL_VISION}")
    return Route(agent, tier, scopes, image=False)                # optional image: text only, usual order


def resolve(s: AiSettings, agent: str, *, have_local: bool, have_cloud: bool, capped: bool = False,
            local_vision: bool = False) -> Route:
    """The route for one agent, or a Route with a reason when no AI may answer it."""
    spec = AGENTS[agent]                                        # KeyError: a programming error, not a user one
    tier = s.tier_for(agent, spec["tier"])
    if s.mode == "none":
        return _off(agent, tier, "AI is off for this project")
    if tier == "off":
        return _off(agent, tier, f"the {spec['label']} agent is set to off on the AI page")
    image = spec["image"]
    if s.mode == "local":
        return _local(agent, tier, image, have_local=have_local, local_vision=local_vision)
    if s.mode == "cloud":
        return _cloud(agent, tier, image, s, have_cloud=have_cloud, capped=capped)
    return _hybrid(agent, tier, image, s, have_local=have_local, have_cloud=have_cloud, capped=capped,
                   local_vision=local_vision)


def effective(s: AiSettings, *, have_local: bool, have_cloud: bool, capped: bool = False,
              local_vision: bool = False) -> list[Route]:
    return [resolve(s, agent, have_local=have_local, have_cloud=have_cloud, capped=capped, local_vision=local_vision)
            for agent in AGENTS]
