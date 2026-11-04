"""`python -m agentqa replan`: apply the answered questions (M1.4, Gate 1).

An answer only takes effect when the Reconciler runs again, and the plan only changes when the Designer runs after it.
This runs those two stages in one process and one Live View recording, without the Writer (no AI cost in Cloud mode,
no long wait in Local mode). Without `--policy` it reuses the rule the last reconcile ran with (the owner's decision,
4 Nov 2026: a run from the app reconciles with "srs_wins", and re-planning it with project.yaml's "ask" brought back
the questions that run had settled); when that run used project.yaml's rule, so does the re-plan."""
from __future__ import annotations

import sys
import time
import traceback
from argparse import Namespace

from agentqa.util import log

STEPS = ("reconcile", "design")
POLICY_KEY = "reconcile_policy"        # store meta: the --policy the plan's reconcile ran with; None means project.yaml's
POLICIES = ("ask", "srs_wins", "app_wins")


def remembered_policy(store) -> str | None:
    """The rule the current plan was made with, if it was one of the real rules (anything else reads as none)."""
    value = store.get_meta(POLICY_KEY)
    return value if value in POLICIES else None


def reconcile(project, store, policy: str | None) -> dict:
    """The reconcile stage, remembering the rule it ran with, once it succeeded, so that a later re-plan reuses it."""
    from agentqa.agents import reconciler
    result = reconciler.reconcile(project, store, policy=policy)
    store.set_meta(POLICY_KEY, policy)
    return result


def cmd_replan(args) -> None:
    from agentqa import cli                       # imported here: cli imports this module for its parser
    p, s = cli._project(args)
    if not getattr(args, "policy", None):
        args = Namespace(**{**vars(args), "policy": remembered_policy(s)})
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
