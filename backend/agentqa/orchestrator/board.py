"""The Live View board (M1.3): the pipeline's stages in order, the agent behind each, owner-readable labels, the helper
agents that run inside a stage, and the three human gates. One table for the command line (which runs the stages)
and the web app (which draws them); pure, no I/O."""
from __future__ import annotations

from types import MappingProxyType

STAGES: tuple[str, ...] = ("analyze", "explore", "reconcile", "write", "design", "generate", "run", "exploratory",
                           "security", "triage", "heal", "report")

STAGE_AGENT = MappingProxyType({
    "analyze": "srs", "explore": "explorer", "reconcile": "reconciler", "write": "writer", "design": "designer",
    "generate": "generator", "run": "executor", "exploratory": "exploratory", "security": "security",
    "triage": "triage", "heal": "healer", "report": "reporter", "import": "importer",
})

LABELS = MappingProxyType({
    "srs": "Requirement Analyst", "explorer": "Explorer", "reconciler": "Reconciler", "writer": "Requirement Writer",
    "designer": "Test Designer", "generator": "Script Generator", "executor": "Executor",
    "exploratory": "Exploratory Tester", "security": "Security Scanner", "triage": "Triage + Bugs", "healer": "Healer",
    "reporter": "Reporter", "analyst": "Functional Test Analyst", "casegen": "Test Case Generator",
    "importer": "Test Importer", "doctor": "Readiness check", "pipeline": "Pipeline", "ai": "AI models",
})

# Helpers run inside a stage's agent; their events are attributed to the stage running at that moment (the
# Requirement Writer and the Reporter also call the Analyst's standardiser), so this only says where they belong.
HELPERS = MappingProxyType({"design": ("analyst", "casegen", "importer")})
HELPER_FALLBACK = MappingProxyType({"importer": "design"})     # runs between stages, so no stage is running then

GATES: tuple[MappingProxyType, ...] = (
    MappingProxyType({"id": "questions", "label": "Questions for you", "after": "reconcile"}),
    MappingProxyType({"id": "plan", "label": "Test plan approval", "before": "generate"}),
    MappingProxyType({"id": "defects", "label": "Defects to confirm", "after": "triage"}),
)


def agent_for(stage: str) -> str:
    """The agent that emits a stage's events (a stage without an entry speaks for itself)."""
    return STAGE_AGENT.get(stage, stage)


def ai_labels() -> dict[str, str]:
    from agentqa.ai import modes                      # pure module (settings only); no provider SDK is imported
    return {key: str(spec["label"]) for key, spec in modes.AGENTS.items()}


def board(roles: list[str] | tuple[str, ...]) -> dict:
    """The board as JSON-ready data for the web app."""
    return {
        "stages": [{"stage": s, "agent": STAGE_AGENT[s], "label": LABELS[STAGE_AGENT[s]]} for s in STAGES],
        "helpers": {stage: list(agents) for stage, agents in HELPERS.items()},
        "helper_fallback": dict(HELPER_FALLBACK),
        "labels": dict(LABELS),
        "gates": [dict(g) for g in GATES],
        "ai_labels": ai_labels(),
        "roles": list(roles),
    }
