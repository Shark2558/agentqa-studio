"""`python -m agentqa replan`: apply the answered questions (M1.4, Gate 1).

An answer only takes effect when the Reconciler runs again, and the plan only changes when the Designer runs after it.
This runs those two stages in one process and one Live View recording, without the Writer (no AI cost in Cloud mode,
no long wait in Local mode). Without `--policy` the Reconciler uses project.yaml's policy, as a pipeline started from
the app does."""
from __future__ import annotations

import sys
import time
import traceback

from agentqa.util import log

STEPS = ("reconcile", "design")


def cmd_replan(args) -> None:
    from agentqa import cli                       # imported here: cli imports this module for its parser
    p, s = cli._project(args)
    cli._live_session(p, "replan")
    job_id = getattr(args, "job_id", None)
    started = time.time()
    try:
        for name in STEPS:
            log(f"[replan] {name} starting")
            cli.stage(name, p, s, args)
            if name == "reconcile":
                cli._questions_gate(s)
        log(f"[replan] done in {time.time() - started:.0f}s")
        cli._set_job(s, job_id, "done", 0)
    except Exception as exc:  # noqa: BLE001 - the traceback goes to the run log; the job is marked failed
        log(f"[replan] FAILED: {exc}")
        traceback.print_exc()
        cli._set_job(s, job_id, "failed", 1)
        sys.exit(1)
