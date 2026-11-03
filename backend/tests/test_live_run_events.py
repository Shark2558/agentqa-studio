"""M1.3: a recording ends honestly. The run shell (not the agents) says when a stage failed or was skipped, which stages
a pipeline covers, and how it ended; a command-line run carries a `running.json` marker for exactly as long as it runs.
The stages themselves are faked: these tests are about the events around them."""
from __future__ import annotations

import json

import pytest

from agentqa import cli, live
from agentqa.orchestrator import board

SECRET_TEXT = "page said Clerk@123 to everyone"


@pytest.fixture
def run(demo, monkeypatch):
    """Runs `python -m agentqa <argv>` on the demo copy with every stage faked; returns (events, markers seen)."""
    p, s = demo
    for var in ("AGENTQA_LIVE_DIR", "AGENTQA_PIPELINE_ID", "AGENTQA_LIVE_SHOTS", "AGENTQA_LIVE_QUALITY"):
        monkeypatch.setenv(var, "set-by-the-run")       # registered, so the values cli.main writes are undone afterwards
        monkeypatch.delenv(var)
    monkeypatch.setattr(live, "_LIVE", None)
    monkeypatch.setattr(cli, "_project", lambda args: (p, s))
    monkeypatch.setattr(cli, "_import_pending", lambda *a, **k: None)
    seen: list[bool] = []

    def go(*argv: str, fail_at: str | None = None) -> list[dict]:
        def fake(name, project, store, args):
            seen.append(any((project.state / "live").glob("*/running.json")))
            if name == fail_at:
                raise RuntimeError(SECRET_TEXT)
            return {"ok": True}
        monkeypatch.setattr(cli, "_stage", fake)
        cli.main([argv[0], "-p", str(p.root), *argv[1:]])
        return recorded(p)

    go.project, go.seen = p, seen
    return go


def recorded(p) -> list[dict]:
    [folder] = list((p.state / "live").iterdir())
    lines = [json.loads(ln) for f in folder.glob("events-*.jsonl") for ln in f.read_text(encoding="utf-8").splitlines()]
    return sorted(lines, key=lambda e: e["seq"])


def pipeline(events: list[dict], kind: str) -> list[dict]:
    return [e for e in events if e["agent"] == "pipeline" and e["kind"] == kind]


def test_a_finished_pipeline_says_which_stages_it_ran_and_that_it_finished(run):
    events = run("pipeline", "--auto-approve")
    [start] = pipeline(events, "stage_start")
    assert start["stages"] == list(board.STAGES) and start["pipeline"].startswith("pl-")
    assert [e["stage"] for e in events if e["kind"] == "stage_start" and e["agent"] != "pipeline"] == list(board.STAGES)
    [end] = pipeline(events, "stage_end")
    assert end["level"] == "ok" and end["outcome"] == "finished" and end is events[-1]


def test_a_from_run_names_only_the_stages_it_covers(run):
    events = run("pipeline", "--auto-approve", "--from", "run")
    assert pipeline(events, "stage_start")[0]["stages"] == list(board.STAGES[board.STAGES.index("run"):])


def test_a_skipped_exploratory_stage_says_so(run):
    run.project.cfg["exploratory"] = {"enabled": False}
    events = run("pipeline", "--auto-approve")
    [skip] = [e for e in events if e["kind"] == "stage_skip"]
    assert skip["agent"] == "exploratory" and skip["stage"] == "exploratory" and "enabled" in skip["why"]
    assert not any(e["kind"] == "stage_start" and e.get("stage") == "exploratory" for e in events)


def test_a_failed_stage_says_it_failed_without_repeating_the_error_text(run):
    with pytest.raises(SystemExit):
        run("pipeline", "--auto-approve", fail_at="explore")
    events = recorded(run.project)
    [failed] = [e for e in events if e["kind"] == "stage_end" and e.get("stage") == "explore"]
    assert failed["agent"] == "explorer" and failed["level"] == "bad" and failed["error"] == "RuntimeError"
    assert failed["title"] == "explore failed (see the run log)"
    [end] = pipeline(events, "stage_end")
    assert end["level"] == "bad" and end["outcome"] == "failed"
    assert SECRET_TEXT not in json.dumps(events) and "Clerk@123" not in json.dumps(events)


def test_stopping_at_the_plan_gate_ends_the_pipeline_with_a_warning(run):
    events = run("pipeline")
    assert pipeline(events, "gate")
    [end] = pipeline(events, "stage_end")
    assert end["level"] == "warn" and "plan" in end["outcome"]
    started = [e["stage"] for e in events if e["kind"] == "stage_start" and e["agent"] != "pipeline"]
    assert started == list(board.STAGES[:board.STAGES.index("generate")])


def test_a_single_stage_that_fails_also_says_so(run):
    with pytest.raises(SystemExit):
        run("write", fail_at="write")
    [failed] = [e for e in recorded(run.project) if e["kind"] == "stage_end"]
    assert failed["agent"] == "writer" and failed["level"] == "bad"


def ended_markers(p) -> list[dict]:
    return [json.loads(f.read_text(encoding="utf-8")) for f in (p.state / "live").glob("*/running.json")]


def test_the_run_marker_exists_while_the_run_works_and_says_ended_after_success(run):
    run("pipeline", "--auto-approve")
    assert run.seen and all(run.seen)
    [marker] = ended_markers(run.project)
    assert marker["ended"]


def test_the_run_marker_says_ended_after_a_failure_too(run):
    with pytest.raises(SystemExit):
        run("pipeline", "--auto-approve", fail_at="reconcile")
    assert run.seen and all(run.seen)
    [marker] = ended_markers(run.project)
    assert marker["ended"]


def test_a_marker_that_cannot_be_written_never_stops_or_fails_the_run(run, monkeypatch):
    from agentqa.orchestrator import live as orchestrator_live

    def in_use(*a, **k):
        raise PermissionError(32, "being used by another process")
    monkeypatch.setattr(orchestrator_live.os, "replace", in_use)
    events = run("pipeline", "--auto-approve")                # no exception, no traceback
    [end] = pipeline(events, "stage_end")
    assert end["level"] == "ok"


def test_a_project_address_with_a_password_in_it_is_never_written_to_the_live_view(run, monkeypatch):
    monkeypatch.setattr(type(run.project), "base_url", property(lambda self: "https://qa:hunter2@portal.example/app"))
    [start] = pipeline(run("pipeline", "--auto-approve"), "stage_start")
    assert start["base_url"] == "https://portal.example/app" and "hunter2" not in json.dumps(start)
