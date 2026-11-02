"""Release readiness: one score (0-100) and a verdict a QA lead can defend.

The score combines three things, each explained in the reasons list:
  50%  tests passed, weighted by priority (P1 counts 3x, P2 2x, P3 1x)
  30%  open defects (each Critical removes half of this part, High a fifth, Medium 5%, Low 1%)
  20%  requirements with at least one test
Verdict: Ready (85+, no open Critical or High), Ready with risks (70+, no open Critical), otherwise Not ready.
"""
from __future__ import annotations

from agentqa.config import Project
from agentqa.store import Store

WEIGHT = {"P1": 3, "P2": 2, "P3": 1}
PENALTY = {"Critical": 0.5, "High": 0.2, "Medium": 0.05, "Low": 0.01}


def compute(project: Project, store: Store, run_id: str | None = None) -> dict:
    run_id = run_id or store.get_meta("last_run")
    results = store.all("SELECT r.category, c.priority FROM results r JOIN cases c ON c.id = r.case_id WHERE r.run_id=?",
                        [run_id]) if run_id else []
    total_w = sum(WEIGHT.get(r["priority"], 1) for r in results if r["category"] != "visual-change")
    pass_w = sum(WEIGHT.get(r["priority"], 1) for r in results if r["category"] == "pass")
    pass_part = pass_w / total_w if total_w else 0.0
    open_def = store.all("SELECT severity FROM defects WHERE status NOT IN ('rejected', 'resolved')")
    by_sev: dict[str, int] = {}
    for d in open_def:
        by_sev[d["severity"]] = by_sev.get(d["severity"], 0) + 1
    defect_part = max(0.0, 1 - sum(PENALTY.get(s, 0) * n for s, n in by_sev.items()))
    req_total = store.scalar("SELECT COUNT(*) FROM requirements") or 0
    covered = {x for c in store.all("SELECT req_ids FROM cases") for x in (c["req_ids"] or [])}
    cov_part = len(covered) / req_total if req_total else 0.0
    score = round(100 * (0.5 * pass_part + 0.3 * defect_part + 0.2 * cov_part))
    crit, high = by_sev.get("Critical", 0), by_sev.get("High", 0)
    if score >= 85 and not crit and not high:
        verdict = "Ready"
    elif score >= 70 and not crit:
        verdict = "Ready with risks"
    else:
        verdict = "Not ready"
    reasons = [
        f"{pass_part:.0%} of tests passed, weighted by priority ({len(results)} test(s) in the latest run)",
        "Open defects: " + (", ".join(f"{n} {s.lower()}" for s, n in sorted(by_sev.items(), key=lambda kv: list(PENALTY).index(kv[0])))
                            if by_sev else "none"),
        f"{len(covered)} of {req_total} requirements have at least one test",
    ]
    if crit:
        reasons.append(f"{crit} open Critical defect(s) block the release")
    changes = store.scalar("SELECT COUNT(*) FROM visual WHERE status='changed'") or 0
    if changes:
        reasons.append(f"{changes} visual change(s) wait for review")
    questions = store.scalar("SELECT COUNT(*) FROM questions WHERE status='open'") or 0
    if questions:
        reasons.append(f"{questions} SRS question(s) are unanswered, so the rules behind them are untested")
    return {"score": score, "verdict": verdict, "reasons": reasons, "parts": {
        "passed": round(pass_part, 3), "defects": round(defect_part, 3), "coverage": round(cov_part, 3)},
        "open_by_severity": by_sev, "run_id": run_id}


def trend(store: Store, n: int = 10) -> list[dict]:
    rows = store.all("SELECT * FROM runs WHERE status='done' ORDER BY started_at DESC LIMIT ?", [n])
    return list(reversed(rows))
