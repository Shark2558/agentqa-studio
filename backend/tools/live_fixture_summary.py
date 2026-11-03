"""Count the Live View fixture's final picture straight from the recorded events (M1.3), independently of the
 frontend model it checks, and write frontend/src/test-fixtures/{live-board.json, live-expected-summary.json}.

    python tools/live_fixture_summary.py
"""
import json, sys
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(root / "backend"))
from agentqa.orchestrator import board as B

fx = root / "backend" / "tests" / "fixtures" / "recordings" / "cli-fixture-pipeline"
events = [json.loads(l) for f in sorted(fx.glob("events-*.jsonl")) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
events.sort(key=lambda e: (e["t"], e["seq"], e["w"]))
roles = next(e["roles"] for e in events if e["agent"] == "pipeline" and e["kind"] == "stage_start")
board = B.board(roles)
(root / "frontend" / "src" / "test-fixtures" / "live-board.json").write_text(json.dumps(board, indent=1), encoding="utf-8")

stage_agents = [s["agent"] for s in board["stages"]]
started = {e["agent"] for e in events if e["kind"] == "stage_start" and e["agent"] != "pipeline"}
ended_bad = {e["agent"] for e in events if e["kind"] == "stage_end" and e.get("level") == "bad"}
ended = {e["agent"] for e in events if e["kind"] == "stage_end" and e["agent"] != "pipeline"}
def state(a):
    if a not in started: return "not-reached"
    if a in ended_bad: return "failed"
    return "done" if a in ended else "did-not-finish"

# AI cost attributed to the stage running at the time (main worker's stage_start / stage_end)
windows = []
for e in events:
    if e["w"] == "main" and e["kind"] == "stage_start" and e["agent"] != "pipeline":
        windows.append([e["agent"], e["t"], None])
    if e["w"] == "main" and e["kind"] == "stage_end" and e["agent"] != "pipeline":
        for w in reversed(windows):
            if w[0] == e["agent"] and w[2] is None: w[2] = e["t"]; break
def running_at(t):
    hits = [w[0] for w in windows if w[1] <= t and (w[2] is None or t <= w[2])]
    return hits[-1] if hits else None
cost, model = Counter(), {}
for e in events:
    if e["agent"] == "ai" and e["kind"] == "cost":
        a = running_at(e["t"]); cost[a] += e["cost_usd"]; model[a] = e["model"]

# tiles: designed cases + executed cases; the last test_end per case wins
tiles = {}
for e in events:
    if e["agent"] == "designer" and e["kind"] == "case" and e.get("case"): tiles.setdefault(e["case"], "not-run")
    if e["agent"] == "executor" and e["kind"] == "test_start" and e.get("case"): tiles[e["case"]] = "no-result"
    if e["agent"] == "executor" and e["kind"] == "test_end" and e.get("case"): tiles[e["case"]] = e["category"]
plan = "approved" if any(e["agent"] == "designer" and e["kind"] == "approve" for e in events) else "pending"
summary = {
    "cards": {a: {"state": state(a), "cost": round(cost[a], 4), "model": model.get(a)} for a in stage_agents},
    "gates": {"questions": sum(1 for e in events if e["kind"] == "question"), "plan": plan,
              "defects": sum(1 for e in events if e["agent"] == "triage" and e["kind"] == "defect")},
    "tiles": dict(sorted(Counter(tiles.values()).items())),
    "ai": {"calls": sum(1 for e in events if e["agent"] == "ai" and e["kind"] == "cost"), "cost": round(sum(cost.values()), 4)},
}
(root / "frontend" / "src" / "test-fixtures" / "live-expected-summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
print(json.dumps(summary, indent=1))
