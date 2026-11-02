"""Live recordings: one folder per run under <project>/.agentqa/live, JSON-lines events plus JPEG screenshots."""
from __future__ import annotations

import base64
import json
import time
from datetime import datetime
from pathlib import Path

from agentqa.config import Project
from agentqa.orchestrator import NotFound
from agentqa.orchestrator.jobs import running
from agentqa.store import Store

CLI_SESSION_LIVE_S = 8          # a command-line run counts as running while its event files are still being written
READ_CHUNK = 4_000_000


def sessions(p: Project, s: Store) -> list[dict]:
    root = p.state / "live"
    if not root.exists():
        return []
    current = running(s)
    out = []
    for d in sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True):
        parts = d.name.split("-")
        is_running = bool(current and d.name.startswith(f"job-{current['id']}-"))
        files = list(d.glob("events-*.jsonl"))
        if d.name.startswith("cli-") and files:
            is_running = time.time() - max(f.stat().st_mtime for f in files) < CLI_SESSION_LIVE_S
        label = (f"Job {parts[1]}: {'-'.join(parts[2:])}" if d.name.startswith("job-")
                 else f"Command line: {'-'.join(parts[3:])}")
        out.append({"id": d.name, "label": label, "running": is_running,
                    "when": datetime.fromtimestamp(d.stat().st_mtime).strftime("%d %b %H:%M"),
                    "shots": len(list((d / "shots").glob("*.jpg"))) if (d / "shots").exists() else 0})
    return out


def session_dir(p: Project, session: str) -> Path:
    d = (p.state / "live" / Path(session).name).resolve()
    if d.parent != (p.state / "live").resolve() or not d.is_dir():
        raise NotFound("No such live session")
    return d


def decode_cursor(cursor: str) -> dict[str, int]:
    try:
        return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode()) if cursor else {}
    except Exception:  # noqa: BLE001 - a bad cursor restarts from the beginning
        return {}


def encode_cursor(offsets: dict[str, int]) -> str:
    return base64.urlsafe_b64encode(json.dumps(offsets).encode()).decode()


def read_events(d: Path, cursor: str = "") -> tuple[list[dict], str]:
    """Events appended since `cursor` (an opaque per-file offset map), sorted by time, and the next cursor."""
    offsets = decode_cursor(cursor)
    events = []
    for f in sorted(d.glob("events-*.jsonl")):
        start = int(offsets.get(f.name, 0))
        with f.open("rb") as fh:
            fh.seek(start)
            chunk = fh.read(READ_CHUNK)
        end = chunk.rfind(b"\n") + 1
        for line in chunk[:end].splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
        offsets[f.name] = start + end
    events.sort(key=lambda e: (e.get("t", 0), e.get("seq", 0)))
    return events, encode_cursor(offsets)


def shot_path(d: Path, name: str) -> Path:
    f = d / "shots" / Path(name).name
    if not f.is_file():
        raise NotFound("No such screenshot")
    return f
