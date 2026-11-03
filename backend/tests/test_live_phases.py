"""M1.3: every live event gets a `phase` (thought, action, result, waiting, lifecycle, meta) when it is read, so the
Live View can show thought -> action -> result without rewriting any agent. The recordings on disk never change, and
no source file may emit a kind the phase table does not know."""
from __future__ import annotations

import ast
import hashlib
import shutil
from pathlib import Path

import pytest

from agentqa.orchestrator import live as L
from agentqa.orchestrator.phases import PHASES, PHASE_NAMES, phase_of

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "recordings" / "cli-fixture-pipeline"


def emitted_kinds() -> dict[str, list[str]]:
    """kind -> where it is emitted, for every live.emit / live.shot call under agentqa/. A kind that is not a string
    literal (or a choice between literals) is reported as '<non-literal>' so the test can name it."""
    found: dict[str, list[str]] = {}
    for f in (ROOT / "agentqa").rglob("*.py"):
        if f.name == "live.py" and f.parent.name == "agentqa":
            continue                                          # the Live class itself passes `kind` through
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("emit", "shot")):
                continue
            idx = 1 if node.func.attr == "emit" else 2
            if len(node.args) <= idx:
                continue
            for kind in _literals(node.args[idx]):
                found.setdefault(kind, []).append(f"{f.relative_to(ROOT)}:{node.lineno}")
    return found


def _literals(arg: ast.expr) -> list[str]:
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return [arg.value]
    if isinstance(arg, ast.IfExp):
        return _literals(arg.body) + _literals(arg.orelse)
    return ["<non-literal>"]


def test_every_kind_the_engine_emits_has_a_phase():
    kinds = emitted_kinds()
    assert "<non-literal>" not in kinds, f"a live event kind must be a literal: {kinds.get('<non-literal>')}"
    missing = {k: v for k, v in kinds.items() if k not in PHASES}
    assert not missing, f"give these kinds a phase in orchestrator/phases.py: {missing}"
    assert len(kinds) >= 41


def test_the_phase_names_are_the_six_the_ui_draws_plus_note():
    assert set(PHASES.values()) <= set(PHASE_NAMES)
    assert PHASE_NAMES == ("thought", "action", "result", "waiting", "lifecycle", "meta", "note")


@pytest.mark.parametrize("agent,kind,phase", [
    ("srs", "rule", "thought"), ("srs", "model", "thought"), ("ai", "model", "meta"), ("ai", "cost", "meta"),
    ("srs", "requirement", "thought"), ("writer", "requirement", "result"),
    ("executor", "navigate", "action"), ("executor", "verdict", "result"), ("executor", "test_start", "thought"),
    ("explorer", "observe", "result"), ("reconciler", "question", "result"), ("pipeline", "gate", "waiting"),
    ("clerk-agent", "assist", "waiting"), ("srs", "stage_start", "lifecycle"), ("exploratory", "stage_skip", "lifecycle"),
    ("generator", "write", "action"), ("triage", "defect", "result"),
])
def test_phase_of_uses_the_kind_and_the_agent_kind_overrides(agent, kind, phase):
    assert phase_of({"agent": agent, "kind": kind}) == phase


def test_an_unknown_kind_from_an_old_recording_is_a_note_never_an_error():
    assert phase_of({"agent": "srs", "kind": "something-new"}) == "note"
    assert phase_of({}) == "note"
    assert phase_of({"agent": 3, "kind": None}) == "note"


def test_read_events_adds_the_phase_and_leaves_the_recording_untouched(tmp_path):
    d = tmp_path / "cli-fixture-pipeline"
    shutil.copytree(FIXTURE, d)
    before = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in d.glob("events-*.jsonl")}
    events, _ = L.read_events(d)
    after = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in d.glob("events-*.jsonl")}
    assert before == after
    assert events and all(e["phase"] in PHASE_NAMES for e in events)
    assert {e["phase"] for e in events} >= {"thought", "action", "result", "waiting", "lifecycle", "meta"}
    first = next(e for e in events if e["kind"] == "rule")
    assert first["phase"] == "thought"
