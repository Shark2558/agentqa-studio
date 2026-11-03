"""Thought -> action -> result for the Live View (M1.3, PRD §7.3), derived when events are read.

Agents keep emitting the kinds they always did (the v0.8 engine is moved, not rewritten); each event is given a
`phase` here instead, so old recordings get one too. `tests/test_live_phases.py` fails when a source file emits a
kind this table does not know. A kind that appears only in an old recording reads as "note".
"""
from __future__ import annotations

from types import MappingProxyType

PHASE_NAMES: tuple[str, ...] = ("thought", "action", "result", "waiting", "lifecycle", "meta", "note")

_BY_PHASE = {
    # what it reads, which rule fired, what it is about to try
    "thought": ("open", "heading", "text", "table", "rule", "ambiguity", "unclear", "persona", "role", "case",
                "test_start", "requirement"),
    # what it did
    "action": ("action", "navigate", "request", "step", "write", "approve", "sync"),
    # what happened
    "result": ("observe", "verdict", "test_end", "status", "defect", "finding", "issue", "skip", "contract", "login",
               "data", "heal", "question"),
    # a person is needed
    "waiting": ("assist", "gate"),
    # a stage or a pass starts, ends or reports progress
    "lifecycle": ("stage_start", "stage_end", "stage_skip", "start", "summary", "progress"),
    # the model in use and what it cost: shown on the cards, not as stream rows
    "meta": ("model", "cost"),
}

PHASES = MappingProxyType({kind: phase for phase, kinds in _BY_PHASE.items() for kind in kinds})

# The same kind means different things for different agents.
OVERRIDES = MappingProxyType({
    ("srs", "model"): "thought",            # "asking the model about FR-3": the Analyst's own step, not the model in use
    ("writer", "requirement"): "result",    # the Writer's rewrite of a requirement; the Analyst only reads them
})


def phase_of(event: dict) -> str:
    """The phase of one event: an (agent, kind) override, else the kind's phase, else "note"."""
    agent, kind = event.get("agent"), event.get("kind")
    if not isinstance(kind, str):
        return "note"
    if isinstance(agent, str) and (agent, kind) in OVERRIDES:
        return OVERRIDES[(agent, kind)]
    return PHASES.get(kind, "note")
