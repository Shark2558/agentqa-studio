"""M1.4 Phase A: `replan` applies answered questions (Reconciler, then Designer, in one run and one recording) without
re-running the Writer; and a continued run says honestly that the plan was approved earlier, and by whom. The stages
themselves are faked."""
from __future__ import annotations

import json

import pytest

from agentqa import cli, live, replan
from agentqa.api.routes_runs import _args
from agentqa.api.schemas import RunIn
from agentqa.orchestrator.gates import changelog

WHO = "owner@example.com (owner)"


@pytest.fixture
def run(demo, monkeypatch):
    p, s = demo
    for var in ("AGENTQA_LIVE_DIR", "AGENTQA_PIPELINE_ID", "AGENTQA_LIVE_SHOTS", "AGENTQA_LIVE_QUALITY"):
        monkeypatch.setenv(var, "set-by-the-run")
        monkeypatch.delenv(var)
    monkeypatch.setattr(live, "_LIVE", None)
    monkeypatch.setattr(cli, "_project", lambda args: (p, s))
    monkeypatch.setattr(cli, "_import_pending", lambda *a, **k: None)
    calls: list[tuple[str, str | None]] = []

    def go(*argv: str, fail_at: str | None = None) -> list[dict]:
        def fake(name, project, store, args):
            calls.append((name, getattr(args, "policy", None)))
            if name == fail_at:
                raise RuntimeError("boom")
            return {"ok": True}
        monkeypatch.setattr(cli, "_stage", fake)
        cli.main([argv[0], "-p", str(p.root), *argv[1:]])
        [folder] = list((p.state / "live").iterdir())
        lines = [json.loads(ln) for f in folder.glob("events-*.jsonl") for ln in f.read_text(encoding="utf-8").splitlines()]
        go.folder = folder
        return sorted(lines, key=lambda e: e["seq"])

    go.project, go.store, go.calls = p, s, calls
    return go


def test_replan_runs_reconcile_then_design_in_one_recording(run):
    events = run("replan")
    assert [c[0] for c in run.calls] == ["reconcile", "design"]
    assert run.folder.name.startswith("cli-") and run.folder.name.endswith("-replan")
    starts = [e["stage"] for e in events if e["kind"] == "stage_start"]
    assert starts == ["reconcile", "design"]
    assert not any(e.get("stage") == "write" for e in events)                    # the Writer does not run again


def test_replan_passes_the_policy_to_the_reconciler(run):
    run("replan", "--policy", "srs_wins")
    assert run.calls[0] == ("reconcile", "srs_wins")


def test_the_reconcile_stage_remembers_the_rule_it_ran_with(demo, monkeypatch):
    """The owner's decision (4 Nov 2026): a re-plan reuses the rule of the run that made the plan."""
    from argparse import Namespace
    p, s = demo
    seen: list[str | None] = []
    monkeypatch.setattr("agentqa.agents.reconciler.reconcile", lambda project, store, policy=None: seen.append(policy) or {"ok": True})
    cli._stage("reconcile", p, s, Namespace(policy="srs_wins"))
    assert seen == ["srs_wins"] and s.get_meta(replan.POLICY_KEY) == "srs_wins"
    cli._stage("reconcile", p, s, Namespace(policy=None))          # project.yaml's rule: nothing to reuse
    assert seen == ["srs_wins", None] and s.get_meta(replan.POLICY_KEY) is None


def test_a_failed_reconcile_keeps_the_rule_the_plan_was_made_with(demo, monkeypatch):
    from argparse import Namespace
    p, s = demo
    s.set_meta(replan.POLICY_KEY, "srs_wins")

    def boom(project, store, policy=None):
        raise RuntimeError("No screens recorded. Run the Explorer first.")
    monkeypatch.setattr("agentqa.agents.reconciler.reconcile", boom)
    with pytest.raises(RuntimeError):
        cli._stage("reconcile", p, s, Namespace(policy=None))
    assert replan.remembered_policy(s) == "srs_wins"
    s.set_meta(replan.POLICY_KEY, "junk")
    assert replan.remembered_policy(s) is None                      # only the three real rules are reused


def test_replan_reuses_the_rule_of_the_run_that_made_the_plan(run):
    run.store.set_meta(replan.POLICY_KEY, "srs_wins")
    run("replan")
    assert run.calls[0] == ("reconcile", "srs_wins")


def test_a_policy_given_to_replan_wins_over_the_remembered_one(run):
    run.store.set_meta(replan.POLICY_KEY, "srs_wins")
    run("replan", "--policy", "ask")
    assert run.calls[0] == ("reconcile", "ask")


def test_replan_marks_its_job_done(run):
    job = run.store.insert("jobs", {"stage": "replan", "status": "running", "started_at": "2026-11-04T10:00:00"})
    run("replan", "--job-id", str(job))
    row = run.store.one("SELECT status, exit_code FROM jobs WHERE id=?", [job])
    assert (row["status"], row["exit_code"]) == ("done", 0)


def test_a_failed_replan_marks_its_job_failed_and_stops(run):
    job = run.store.insert("jobs", {"stage": "replan", "status": "running", "started_at": "2026-11-04T10:00:00"})
    with pytest.raises(SystemExit):
        run("replan", "--job-id", str(job), fail_at="reconcile")
    assert run.store.one("SELECT status FROM jobs WHERE id=?", [job])["status"] == "failed"
    assert [c[0] for c in run.calls] == ["reconcile"]


def test_the_runs_api_accepts_replan():
    assert RunIn(scope="replan").scope == "replan"
    assert _args(RunIn(scope="replan")) == (["replan"], "replan")
    assert _args(RunIn(scope="replan", policy="srs_wins")) == (["replan", "--policy", "srs_wins"], "replan")


def _approved(store, at: str = "2026-11-04T09:30:00") -> None:
    store.insert("plan", {"id": 1, "approved": 1, "approved_at": at, "summary": {"digest": "abc"}}, replace=True)


def test_a_continued_run_says_the_plan_was_approved_earlier_and_by_whom(run):
    _approved(run.store)
    changelog.record(run.store, "plan", "-", "approved the plan: 3 approved, 0 rejected", "", WHO)
    run.store.exec("UPDATE change_log SET at='2026-11-04T09:30:00'")     # written in the second the plan was approved
    events = run("pipeline", "--from", "generate")
    [line] = [e for e in events if e["agent"] == "designer" and e["kind"] == "approve"]
    assert line["title"] == f"Test plan approved earlier, on 2026-11-04 09:30 by {WHO}" and line["level"] == "ok"
    assert "generate" in [c[0] for c in run.calls]


def test_without_a_logged_approval_the_line_names_no_one(run):
    _approved(run.store)
    events = run("pipeline", "--from", "generate")
    [line] = [e for e in events if e["agent"] == "designer" and e["kind"] == "approve"]
    assert line["title"] == "Test plan approved earlier, on 2026-11-04 09:30"


def test_an_auto_approved_run_does_not_claim_an_earlier_approval(run):
    _approved(run.store)
    events = run("pipeline", "--from", "generate", "--auto-approve")
    assert not [e for e in events if e["agent"] == "designer" and "earlier" in e["title"]]


def test_an_approval_logged_before_the_current_one_names_no_one(run):
    """Alice approved in the app; a re-design cleared it; the command line approved again without a log row."""
    changelog.record(run.store, "plan", "-", "approved the plan: 3 approved, 0 rejected", "", WHO)
    run.store.exec("UPDATE change_log SET at='2026-11-04T08:00:00'")
    _approved(run.store, at="2026-11-04T09:30:00")
    events = run("pipeline", "--from", "generate")
    [line] = [e for e in events if e["agent"] == "designer" and e["kind"] == "approve"]
    assert line["title"] == "Test plan approved earlier, on 2026-11-04 09:30"


def test_a_failed_replan_leaves_its_traceback_in_the_log(run, capsys):
    with pytest.raises(SystemExit):
        run("replan", fail_at="design")
    out = capsys.readouterr()
    assert "Traceback" in out.out + out.err and "[replan] FAILED" in out.out
