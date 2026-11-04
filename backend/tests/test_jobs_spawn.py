"""M1.4 security review: checking that nothing runs and recording the new job happen as one step, so a double-click
on "Apply my answers" (or two people at once) cannot start two jobs for one project."""
from __future__ import annotations

import threading
import time

from agentqa.orchestrator import Busy, jobs
from agentqa.store import Store


class FakeProcess:
    pid = 4242

    def poll(self):
        return None


def test_two_starts_at_the_same_moment_start_one_job(demo, monkeypatch):
    p, _ = demo
    monkeypatch.setattr(jobs, "PROCS", {})
    monkeypatch.setattr(jobs.subprocess, "Popen", lambda *a, **k: FakeProcess())
    real = jobs.running

    def slow(store):
        time.sleep(0.2)                       # widen the gap between "nothing runs" and "record the job"
        return real(store)
    monkeypatch.setattr(jobs, "running", slow)
    results: list[object] = []

    def start() -> None:
        store = Store(p.db_path)
        try:
            results.append(jobs.spawn(p, store, ["replan"], "replan"))
        except Busy:
            results.append("busy")
        finally:
            store.close()
    threads = [threading.Thread(target=start) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(type(r).__name__ for r in results) == ["int", "str"]
    store = Store(p.db_path)
    try:
        assert store.scalar("SELECT COUNT(*) FROM jobs") == 1
    finally:
        store.close()
