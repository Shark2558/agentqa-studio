"""M1.3: "is this run still going?" asks only about that run: a job session by its job row and process, a command-line
session by its `running.json` marker and process (so a model that thinks for minutes does not end the stream), and
an old folder by the 8-second rule. It never lists every session or counts screenshots."""
from __future__ import annotations

import json
import os
import pathlib
import time

import pytest

from agentqa.orchestrator import jobs
from agentqa.orchestrator import live as L


def session(p, name: str) -> pathlib.Path:
    d = p.state / "live" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "events-main.jsonl").write_text(json.dumps({"t": time.time(), "seq": 1, "w": "main", "agent": "srs",
                                                      "kind": "start", "title": "go"}) + "\n", encoding="utf-8")
    return d


def age(d: pathlib.Path, seconds: float) -> None:
    old = time.time() - seconds
    for f in d.glob("events-*.jsonl"):
        os.utime(f, (old, old))


def job(s, status: str = "running", pid: int = 4242) -> int:
    return s.insert("jobs", {"stage": "pipeline", "status": status, "started_at": "2026-11-03T00:00:00",
                             "log_path": "", "pid": pid})


def test_a_job_session_runs_while_its_row_says_running_and_its_process_lives(demo, monkeypatch):
    p, s = demo
    monkeypatch.setattr(jobs, "pid_alive", lambda pid: True)
    done = job(s, "done")
    live_job = job(s)
    session(p, f"job-{live_job}-pipeline")
    session(p, f"job-{done}-explore")
    assert L.is_running(p, f"job-{live_job}-pipeline") is True
    assert L.is_running(p, f"job-{done}-explore") is False


def test_a_job_whose_process_died_is_not_running_and_is_marked_failed(demo, monkeypatch):
    p, s = demo
    monkeypatch.setattr(jobs, "pid_alive", lambda pid: False)
    jid = job(s)
    session(p, f"job-{jid}-pipeline")
    assert L.is_running(p, f"job-{jid}-pipeline") is False
    assert s.one("SELECT status, exit_code FROM jobs WHERE id=?", [jid]) == {"status": "failed", "exit_code": -1}


def test_job_running_checks_one_job_not_the_latest_one(demo, monkeypatch):
    p, s = demo
    monkeypatch.setattr(jobs, "pid_alive", lambda pid: True)
    first, second = job(s), job(s)
    assert jobs.job_running(s, first) is True and jobs.job_running(s, second) is True
    assert jobs.job_running(s, 999) is False


def test_a_command_line_run_with_its_marker_stays_running_through_a_long_silence(demo, monkeypatch):
    p, _ = demo
    d = session(p, "cli-20261103-101010-pipeline")
    marker = L.mark_running(d)
    assert json.loads(marker.read_text(encoding="utf-8"))["pid"] == os.getpid()
    age(d, 600)
    assert L.is_running(p, d.name) is True
    monkeypatch.setattr(jobs, "pid_alive", lambda pid: False)
    assert L.is_running(p, d.name) is False


def test_a_finished_run_reads_as_finished_at_once_even_while_its_files_are_fresh(demo):
    p, _ = demo
    d = session(p, "cli-20261103-101111-pipeline")
    L.mark_running(d)
    L.mark_ended(d, os.getpid())
    marker = json.loads((d / L.RUN_MARKER).read_text(encoding="utf-8"))
    assert marker["pid"] == os.getpid() and marker["ended"]
    assert L.is_running(p, d.name) is False                # no 8-second "still running" window after the end
    L.mark_ended(d, os.getpid())                           # ending twice is harmless


def test_ending_never_touches_another_processes_marker(demo):
    p, _ = demo
    d = session(p, "cli-20261103-102222-pipeline")
    (d / L.RUN_MARKER).write_text(json.dumps({"pid": 4242, "started": "2026-11-03T10:00:00"}), encoding="utf-8")
    L.mark_ended(d, os.getpid())
    assert "ended" not in json.loads((d / L.RUN_MARKER).read_text(encoding="utf-8"))


def test_a_marker_that_cannot_be_written_never_raises(demo, monkeypatch):
    p, _ = demo
    d = session(p, "cli-20261103-103333-pipeline")

    def in_use(*a, **k):
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")
    monkeypatch.setattr(L.os, "replace", in_use)
    assert L.mark_running(d) is None
    L.mark_ended(d, os.getpid())
    assert not list(d.glob(".*.tmp")) and not list(d.glob("*.tmp"))   # no half-written leftovers


@pytest.mark.parametrize("pid", [2 ** 40, -5, 0, True, "4242", 1.5, None])
def test_a_marker_with_an_impossible_pid_never_breaks_the_listing(demo, pid):
    p, s = demo
    d = session(p, "cli-20261103-104444-pipeline")
    (d / L.RUN_MARKER).write_text(json.dumps({"pid": pid}), encoding="utf-8")
    age(d, 60)
    assert L.is_running(p, d.name) is False
    assert any(x["id"] == d.name and x["running"] is False for x in L.sessions(p, s))


def test_pid_alive_says_no_to_pids_no_system_can_have():
    assert not any(jobs.pid_alive(pid) for pid in (2 ** 40, 2 ** 31, -1, 0))
    assert jobs.pid_alive(os.getpid()) is True


def test_checking_a_live_job_reads_one_row_without_opening_the_project_store(demo, monkeypatch):
    p, s = demo
    monkeypatch.setattr(jobs, "pid_alive", lambda pid: True)
    jid = job(s)
    session(p, f"job-{jid}-pipeline")

    def no_store(*a, **k):
        raise AssertionError("opened the full project store")
    monkeypatch.setattr(L, "Store", no_store)
    assert L.is_running(p, f"job-{jid}-pipeline") is True


def test_without_a_marker_a_command_line_run_counts_only_while_its_files_change(demo):
    p, _ = demo
    d = session(p, "cli-20261103-111111-write")
    assert L.is_running(p, d.name) is True
    age(d, 60)
    assert L.is_running(p, d.name) is False


def test_a_broken_marker_falls_back_to_the_file_age_rule(demo):
    p, _ = demo
    d = session(p, "cli-20261103-121212-write")
    (d / L.RUN_MARKER).write_text("{not json", encoding="utf-8")
    age(d, 60)
    assert L.is_running(p, d.name) is False


def test_is_running_never_lists_sessions_or_counts_screenshots(demo, monkeypatch):
    p, s = demo
    d = session(p, "cli-20261103-131313-pipeline")
    (d / "shots").mkdir()
    (d / "shots" / "main-00001.jpg").write_bytes(b"jpg")
    monkeypatch.setattr(L, "sessions", lambda *a, **k: (_ for _ in ()).throw(AssertionError("listed sessions")))
    real_glob = pathlib.Path.glob

    def guarded(self, pattern, *a, **k):
        assert not pattern.endswith(".jpg"), "counted screenshots"
        return real_glob(self, pattern, *a, **k)

    monkeypatch.setattr(pathlib.Path, "glob", guarded)
    assert L.is_running(p, d.name) is True


def test_sessions_counts_screenshots_only_when_asked_and_says_which_have_events(demo):
    p, s = demo
    d = session(p, "cli-20261103-141414-pipeline")
    (d / "shots").mkdir()
    (d / "shots" / "main-00001.jpg").write_bytes(b"jpg")
    (p.state / "live" / "job-77-sync").mkdir(parents=True)
    listed = {x["id"]: x for x in L.sessions(p, s)}
    assert listed[d.name]["shots"] == 1 and listed[d.name]["has_events"] is True
    assert listed["job-77-sync"]["has_events"] is False
    quick = {x["id"]: x for x in L.sessions(p, s, count_shots=False)}
    assert "shots" not in quick[d.name] and quick[d.name]["has_events"] is True
