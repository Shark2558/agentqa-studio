"""Trim a real Live View recording into the small fixture the Live View tests replay (M1.3).

    python tools/make_live_fixture.py <recording folder> [--out tests/fixtures/recordings/cli-fixture-pipeline]
                                      [--frontend ../frontend/src/test-fixtures/live-demo.json]

Keeps every agent and every kind of event, caps the repetitive ones, keeps a few whole test cases per browser
worker, copies at most 12 screenshots (the rest lose their `shot`), cuts absolute paths from the recording machine
down to the part inside the project, and adds five AI lines shaped like a Cloud run (two `model`, three per-call
`cost`) so a No-AI recording still exercises model and cost. Refuses to write anything (exit 1) if a demo account
password, an unmasked secret-named field or an absolute path is left, and only ever replaces a folder that is itself
a fixture (exit 2): never the recording, a folder inside it, or a folder holding anything else.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WORKERS = ("main", "gw0", "gw1", "tests-login")
ALWAYS = {"stage_start", "stage_end", "stage_skip", "gate", "approve", "defect", "model", "cost", "contract", "assist",
          "summary", "start", "open", "write", "question", "finding", "issue", "skip", "role", "data", "table",
          "progress", "heal", "sync", "login"}
CAP_PER_AGENT_KIND = 8          # every other kind: the first few of each agent
CASES_PER_WORKER = 5            # whole executor test cases kept per browser worker (plus every non-passing one, capped)
MAX_FAILED_CASES = 4
MAX_SHOTS = 12
SECRET_FIELDS = re.compile(r"password|passwd|pwd|otp|token|secret", re.I)
MASK = "•" * 8
# a drive letter, a network share, or a home folder, not preceded by part of a word or a URL
ABSOLUTE = re.compile(r"(?<![\w/])[A-Za-z]:[\\/]|(?<![\w/])\\\\[^\\\s]+\\|(?<![\w.:/-])/(?:Users|home)/")
WHOLE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/(?:Users|home)/)")
PROJECT_FOLDERS = ("reports", "runs", "tests", "visual", "srs", "imports", ".agentqa")
FIXTURE_FILE = re.compile(r"^events-[\w.-]+\.jsonl$")


def load(folder: Path, worker: str) -> list[dict]:
    f = folder / f"events-{worker}.jsonl"
    if not f.is_file():
        return []
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]


def keep_cases(events: list[dict]) -> set[str]:
    """The executor cases to keep whole: the first few, and the first few that did not pass."""
    ends = [e for e in events if e.get("kind") == "test_end" and e.get("case")]
    first = [e["case"] for e in ends[:CASES_PER_WORKER]]
    failed = [e["case"] for e in ends if e.get("category") != "passed"][:MAX_FAILED_CASES]
    return set(first + failed)


def trim(events: list[dict]) -> list[dict]:
    cases = keep_cases(events)
    seen: Counter = Counter()
    out = []
    for e in events:
        if e.get("agent") == "executor" and e.get("case"):
            if e["case"] in cases:
                out.append(e)
            continue
        key = (e.get("agent"), e.get("kind"))
        seen[key] += 1
        if e.get("kind") in ALWAYS or seen[key] <= CAP_PER_AGENT_KIND:
            out.append(e)
    return out


def choose_shots(by_worker: dict[str, list[dict]]) -> set[str]:
    """Up to MAX_SHOTS screenshots spread over the agents that take them, failures first."""
    with_shot = [e for evs in by_worker.values() for e in evs if e.get("shot")]
    with_shot.sort(key=lambda e: (e.get("level") != "bad", e.get("t", 0)))
    chosen: list[str] = []
    per_agent: Counter = Counter()
    for e in with_shot:
        if len(chosen) >= MAX_SHOTS:
            break
        if per_agent[e["agent"]] < MAX_SHOTS // 3:
            per_agent[e["agent"]] += 1
            chosen.append(e["shot"])
    return set(chosen)


def stage_window(events: list[dict], stage: str) -> tuple[float, float]:
    start = next(e["t"] for e in events if e.get("kind") == "stage_start" and e.get("stage") == stage)
    end = next((e["t"] for e in events if e.get("kind") == "stage_end" and e.get("stage") == stage), start + 1)
    return start, end


def cloud_lines(main: list[dict]) -> list[dict]:
    """Two `model` and three per-call `cost` lines, as a Cloud (Anthropic) run writes them, inside real stages."""
    seq = max(e["seq"] for e in main)
    a0, a1 = stage_window(main, "analyze")
    w0, w1 = stage_window(main, "write")
    rows = [
        (a0 + (a1 - a0) * 0.3, "model", "Requirement Analyst: claude-sonnet-5-5 (balanced)",
         {"agent_key": "srs", "tier": "balanced", "mode": "cloud", "scopes": ["cloud"]}),
        (a0 + (a1 - a0) * 0.6, "cost", "Requirement Analyst: claude-sonnet-5-5 · $0.0052",
         {"agent_key": "srs", "tier": "balanced", "scope": "cloud", "provider": "anthropic", "model": "claude-sonnet-5-5",
          "input_tokens": 1650, "output_tokens": 190, "cost_usd": 0.0052, "estimated": False, "ms": 2210, "ok": True}),
        (w0 + (w1 - w0) * 0.2, "model", "Requirement Writer: claude-opus-5-5 (strong)",
         {"agent_key": "req_writer", "tier": "strong", "mode": "cloud", "scopes": ["cloud"]}),
        (w0 + (w1 - w0) * 0.5, "cost", "Requirement Writer: claude-opus-5-5 · $0.0610",
         {"agent_key": "req_writer", "tier": "strong", "scope": "cloud", "provider": "anthropic", "model": "claude-opus-5-5",
          "input_tokens": 4100, "output_tokens": 2230, "cost_usd": 0.061, "estimated": False, "ms": 41800, "ok": True}),
        (w0 + (w1 - w0) * 0.8, "cost", "Requirement Writer: claude-opus-5-5 · $0.0587",
         {"agent_key": "req_writer", "tier": "strong", "scope": "cloud", "provider": "anthropic", "model": "claude-opus-5-5",
          "input_tokens": 3900, "output_tokens": 2155, "cost_usd": 0.0587, "estimated": False, "ms": 39950, "ok": True}),
    ]
    return [{"t": round(t, 3), "seq": seq + i + 1, "w": "main", "agent": "ai", "kind": kind, "title": title, **fields}
            for i, (t, kind, title, fields) in enumerate(rows)]


def demo_passwords() -> set[str]:
    """Every password in the demo project's settings, found by parsing them (not by pattern), at any depth."""
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).lower() in ("password", "passwd", "pwd") and isinstance(value, (str, int)):
                    found.add(str(value))
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(yaml.safe_load((ROOT / "demo" / "project.yaml").read_text(encoding="utf-8")))
    return found


def _unmasked(node, where: str = "") -> list[str]:
    """Secret-named fields at any depth whose value is not the mask."""
    if isinstance(node, dict):
        out = [f"{where}.{k}" for k, v in node.items() if SECRET_FIELDS.search(str(k)) and isinstance(v, str)
               and v and v != MASK]
        return out + [x for k, v in node.items() for x in _unmasked(v, f"{where}.{k}")]
    if isinstance(node, list):
        return [x for i, v in enumerate(node) for x in _unmasked(v, f"{where}[{i}]")]
    return []


def secret_problems(events: list[dict], passwords: set[str]) -> list[str]:
    """Anything that must not reach git: a demo password, an unmasked secret-named field, an absolute path."""
    problems = []
    for e in events:
        where, blob = f"{e.get('w')}:{e.get('seq')}", json.dumps(e, ensure_ascii=False)
        problems += [f"{where} contains a demo password" for pw in passwords if pw in blob]
        problems += [f"{where} contains an absolute path"] if ABSOLUTE.search(blob) else []
        problems += [f"{where} field {field} is not masked" for field in _unmasked(e)]
    return problems


def _relative(path: str) -> str:
    """An absolute path from the recording machine, cut to the part inside the project (else its file name)."""
    parts = [p for p in re.split(r"[\\/]+", path) if p]
    if "projects" in parts:
        start = len(parts) - 1 - parts[::-1].index("projects") + 2       # skip "projects/<name>"
        if start < len(parts):
            return "/".join(parts[start:])
    inside = [i for i, p in enumerate(parts) if p in PROJECT_FOLDERS]
    return "/".join(parts[inside[-1]:]) if inside else parts[-1]


def strip_paths(node):
    if isinstance(node, dict):
        return {k: strip_paths(v) for k, v in node.items()}
    if isinstance(node, list):
        return [strip_paths(v) for v in node]
    return _relative(node) if isinstance(node, str) and WHOLE_PATH.match(node) else node


def replaceable(out: Path, src: Path) -> bool:
    """Whether `out` may be (re)written: not the recording, not inside it, not holding it, and either absent or a
    fixture already (event files and a shots folder of JPEGs, nothing else)."""
    out, src = out.resolve(), src.resolve()
    if out == src or out.is_relative_to(src) or src.is_relative_to(out):
        return False
    if not out.exists():
        return True
    return out.is_dir() and all(
        (f.is_file() and FIXTURE_FILE.match(f.name)) or
        (f.is_dir() and f.name == "shots" and all(x.suffix == ".jpg" for x in f.iterdir()))
        for f in out.iterdir())


def write(out: Path, src: Path, by_worker: dict[str, list[dict]], shots: set[str]) -> None:
    if out.exists():
        shutil.rmtree(out)                                    # `replaceable` said it holds a fixture and nothing else
    (out / "shots").mkdir(parents=True)
    for worker, events in by_worker.items():
        lines = [json.dumps(e, ensure_ascii=False) for e in sorted(events, key=lambda e: e["seq"])]
        (out / f"events-{worker}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name in sorted(shots):
        shutil.copy(src / "shots" / name, out / "shots" / name)


def build(src: Path) -> tuple[dict[str, list[dict]], set[str]]:
    by_worker = {w: [strip_paths(e) for e in trim(load(src, w))] for w in WORKERS}
    by_worker = {w: evs for w, evs in by_worker.items() if evs}
    by_worker["main"] = by_worker["main"] + cloud_lines(by_worker["main"])
    shots = choose_shots(by_worker)
    by_worker = {w: [e if not e.get("shot") or e["shot"] in shots else _without_shot(e) for e in evs]
                 for w, evs in by_worker.items()}
    return by_worker, shots


def _without_shot(event: dict) -> dict:
    return {k: v for k, v in event.items() if k not in ("shot", "box")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("recording", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "tests" / "fixtures" / "recordings" / "cli-fixture-pipeline")
    ap.add_argument("--frontend", type=Path, default=ROOT.parent / "frontend" / "src" / "test-fixtures" / "live-demo.json")
    args = ap.parse_args(argv)
    if not replaceable(args.out, args.recording):
        print(f"Refusing to write to {args.out}: it is the recording, inside it, or a folder that is not a fixture")
        return 2
    passwords = demo_passwords()
    if not passwords:
        print("Refusing to write the fixture: no demo password found in demo/project.yaml to check it against")
        return 1
    by_worker, shots = build(args.recording)
    everything = [e for evs in by_worker.values() for e in evs]
    problems = secret_problems(everything, passwords)
    if problems:
        print("Refusing to write the fixture:\n  " + "\n  ".join(problems[:20]))
        return 1
    write(args.out, args.recording, by_worker, shots)
    from agentqa.orchestrator.live import read_events
    served, _ = read_events(args.out)                    # what the API serves (sorted, with `phase` once M1.3 adds it)
    args.frontend.parent.mkdir(parents=True, exist_ok=True)
    args.frontend.write_text(json.dumps({"session": args.out.name, "events": served}, ensure_ascii=False, indent=0),
                             encoding="utf-8")
    kinds = Counter((e["agent"], e["kind"]) for e in everything)
    print(f"{len(everything)} events in {len(by_worker)} files, {len(shots)} screenshots, {len(kinds)} agent/kind pairs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
