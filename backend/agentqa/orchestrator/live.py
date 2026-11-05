"""Live recordings: one folder per run under <project>/.agentqa/live, JSON-lines events plus JPEG screenshots.

Reading adds each event's `phase` (thought / action / result / …, `phases.py`); the files are never changed. The
cursor the browser sends back is checked: only this run's event files, offsets inside the file. "Is it running?" asks
about one run only: a job by its row and process, a command-line run by its `running.json` marker and process, an
older folder by whether its files changed in the last few seconds."""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

from agentqa.config import Project
from agentqa.orchestrator import NotFound
from agentqa.orchestrator import jobs as _jobs
from agentqa.orchestrator.phases import phase_of
from agentqa.store import Store

log = logging.getLogger("agentqa.live")
CLI_SESSION_LIVE_S = 8          # a command-line run without a marker counts as running while its files still change
READ_CHUNK = 4_000_000
RUN_MARKER = "running.json"
MARKER_RETRIES, MARKER_RETRY_S = 3, 0.05
EVENT_FILE = re.compile(r"^events-[\w.-]{1,64}\.jsonl$")
JOB_SESSION = re.compile(r"^job-(\d+)-")
MAX_CURSOR_FILES = 64


def sessions(p: Project, s: Store, count_shots: bool = True) -> list[dict]:
    """Every recorded run, newest first. Counting screenshots walks every shots folder, so the API leaves it out."""
    root = p.state / "live"
    if not root.exists():
        return []
    current = _jobs.running(s)
    stamped = [(_mtime(d), d) for d in root.iterdir() if d.is_dir() and not d.is_symlink()]
    described = (_describe(d, when, current, count_shots) for when, d in sorted(stamped, reverse=True) if when)
    return [item for item in described if item]


def _mtime(d: Path) -> float:
    try:
        return d.stat().st_mtime
    except OSError:                                           # pruned while the list was being made
        return 0.0


def _describe(d: Path, when: float, current_job: dict | None, count_shots: bool) -> dict | None:
    parts = d.name.split("-")
    label = (f"Job {parts[1]}: {'-'.join(parts[2:])}" if d.name.startswith("job-")
             else f"Command line: {'-'.join(parts[3:])}")
    try:
        if d.name.startswith("job-"):
            running = bool(current_job and d.name.startswith(f"job-{current_job['id']}-"))
        else:
            running = _cli_running(d)
        item = {"id": d.name, "label": label, "running": running,
                "when": datetime.fromtimestamp(when).strftime("%d %b %H:%M"), "has_events": _has_events(d)}
        if count_shots:
            item["shots"] = len(list((d / "shots").glob("*.jpg"))) if (d / "shots").exists() else 0
    except FileNotFoundError:                                 # pruned while it was being described
        return None
    return item


def _event_files(d: Path) -> list[Path]:
    return sorted(f for f in d.glob("events-*.jsonl")
                  if EVENT_FILE.match(f.name) and f.is_file() and not f.is_symlink())


def _has_events(d: Path) -> bool:
    return any(f.stat().st_size > 0 for f in _event_files(d))


def session_dir(p: Project, session: str) -> Path:
    d = (p.state / "live" / Path(session).name).resolve()
    if d.parent != (p.state / "live").resolve() or not d.is_dir():
        raise NotFound("No such live session")
    return d


# ---- is it running? -------------------------------------------------------------------------------------------

def is_running(p: Project, session: str) -> bool:
    """Whether this one run is still going; safe in any thread. A job costs one bare query (the full store is opened
    only to mark a job whose process died as failed)."""
    d = session_dir(p, session)
    job = JOB_SESSION.match(d.name)
    if not job:
        return _cli_running(d)
    job_id = int(job.group(1))
    row = _jobs.peek(p.db_path, job_id)
    if not row or row["status"] != "running":
        return False
    if _jobs.process_alive(job_id, row["pid"]):
        return True
    store = Store(p.db_path)
    try:
        return _jobs.job_running(store, job_id)               # marks it failed
    finally:
        store.close()


def cli_run_going(p: Project) -> bool:
    """Whether a command-line run of this project is going (a run that is not a job: Pause must still reach it)."""
    root = p.state / "live"
    try:
        folders = [d for d in root.iterdir() if not JOB_SESSION.match(d.name)]
    except OSError:                                           # no recordings yet
        return False
    return any(_cli_folder_running(d) for d in folders)


def _cli_folder_running(d: Path) -> bool:
    try:
        return d.is_dir() and not d.is_symlink() and _cli_running(d)
    except OSError:                                           # pruned while it was read: that one is not running
        return False


def _cli_running(d: Path) -> bool:
    marker = _marker(d)
    if marker is not None:
        return "ended" not in marker and _jobs.pid_alive(marker["pid"])
    files = _event_files(d)
    return bool(files) and time.time() - max(f.stat().st_mtime for f in files) < CLI_SESSION_LIVE_S


def _marker(d: Path) -> dict | None:
    """The run marker when it is well formed (an object with a whole, possible pid); otherwise None."""
    try:
        data = json.loads((d / RUN_MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or type(data.get("pid")) is not int or not 0 < data["pid"] <= _jobs.MAX_PID:
        return None
    return data


def mark_running(folder: Path) -> Path | None:
    """Write the marker that keeps a command-line run "running" while its process lives. Best effort: a marker that
    cannot be written leaves the run to the file-age rule; it never stops the run."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        return _write_marker(folder, {"pid": os.getpid(), "started": _now()})
    except OSError as exc:
        log.warning("live run marker not written in %s: %s", folder.name, type(exc).__name__)
        return None


def mark_ended(folder: Path, pid: int) -> None:
    """Say the run of process `pid` is over (the marker stays, so a finished run never reads as running). Another
    process's marker is left alone; a marker that cannot be written now is left to the pid check."""
    marker = _marker(folder)
    if not marker or marker["pid"] != pid or "ended" in marker:
        return
    try:
        _write_marker(folder, {**marker, "ended": _now()})
    except OSError as exc:
        log.warning("live run marker not ended in %s: %s", folder.name, type(exc).__name__)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _write_marker(folder: Path, data: dict) -> Path:
    """Write the marker whole or not at all: a temporary file, then an atomic replace (retried briefly, because on
    Windows a reader holding the file open makes the replace fail for a moment)."""
    marker, tmp = folder / RUN_MARKER, folder / f".{RUN_MARKER}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(data), encoding="utf-8")
    try:
        for _ in range(MARKER_RETRIES):
            try:
                os.replace(tmp, marker)
                return marker
            except PermissionError:
                time.sleep(MARKER_RETRY_S)
        os.replace(tmp, marker)
        return marker
    finally:
        tmp.unlink(missing_ok=True)


# ---- events and the cursor ------------------------------------------------------------------------------------

def decode_cursor(cursor: str) -> dict:
    """The cursor's raw offset map, or {} when it is not one (a bad cursor restarts from the beginning)."""
    try:
        raw = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode()) if cursor else {}
    except Exception:  # noqa: BLE001 - anything undecodable is simply not a cursor
        return {}
    return raw if isinstance(raw, dict) else {}


def encode_cursor(offsets: dict[str, int]) -> str:
    return base64.urlsafe_b64encode(json.dumps(offsets).encode()).decode()


def _offsets(cursor: str, files: list[Path]) -> dict[str, int]:
    """Only this run's event files, whole non-negative offsets clamped to the file's size; too many entries: none."""
    raw = decode_cursor(cursor)
    if len(raw) > MAX_CURSOR_FILES:
        return {}
    sizes = {f.name: f.stat().st_size for f in files}
    return {name: min(value, sizes[name]) for name, value in raw.items()
            if name in sizes and type(value) is int and value >= 0}


def _order(e: dict) -> tuple[float, int]:
    t, seq = e.get("t"), e.get("seq")
    return (t if isinstance(t, (int, float)) else 0, seq if isinstance(seq, int) else 0)


def read_events(d: Path, cursor: str = "") -> tuple[list[dict], str]:
    """Events appended since `cursor` (an opaque per-file offset map), each with its `phase`, sorted by time, and the
    next cursor."""
    files = _event_files(d)
    offsets = _offsets(cursor, files)
    events: list[dict] = []
    following: dict[str, int] = {}
    for f in files:
        start = offsets.get(f.name, 0)
        with f.open("rb") as fh:
            fh.seek(start)
            chunk = fh.read(READ_CHUNK)
        end = chunk.rfind(b"\n") + 1
        for line in chunk[:end].splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append({**event, "phase": phase_of(event)})
        following[f.name] = start + end
    events.sort(key=_order)
    return events, encode_cursor(following)


def shot_path(d: Path, name: str) -> Path:
    f = d / "shots" / Path(name).name
    if not f.is_file() or f.is_symlink():
        raise NotFound("No such screenshot")
    return f
