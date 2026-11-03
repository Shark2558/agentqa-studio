"""Jobs: long stages run as separate `python -m agentqa …` processes so a crash in one cannot take the UI down."""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from agentqa.config import Project
from agentqa.orchestrator import Busy
from agentqa.orchestrator.projects import ROOT
from agentqa.store import Store, now

PROCS: dict[int, subprocess.Popen] = {}       # jobs this process started, by job id
KEEP_LIVE_SESSIONS = 15
API_SECRET_PREFIXES = ("AGENTQA_SECRET_KEY", "AGENTQA_OWNER_")   # the API's secrets; a stage never needs them
STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MAX_PID = 2 ** 31 - 1
PEEK_TIMEOUT_S = 2


def pid_alive(pid: int) -> bool:
    if type(pid) is not int or not 0 < pid <= MAX_PID:      # a pid no system can have (a corrupt or planted marker)
        return False
    if os.name == "nt":  # os.kill(pid, 0) would terminate the process on Windows
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def peek(db_path: Path, job_id: int) -> dict | None:
    """A job's status and pid from one bare query, without the store's set-up (the Live View asks every half
    second). None when the project has no database yet or it cannot be read just now."""
    if not db_path.is_file():
        return None
    try:
        with closing(sqlite3.connect(str(db_path), timeout=PEEK_TIMEOUT_S)) as conn:
            row = conn.execute("SELECT status, pid FROM jobs WHERE id=?", [job_id]).fetchone()
    except sqlite3.Error:
        return None
    return {"status": row[0], "pid": row[1]} if row else None


def process_alive(job_id: int, pid: int | None) -> bool:
    """Whether a job's process lives: the handle when this server started it, else its pid."""
    proc = PROCS.get(job_id)
    return (proc.poll() is None) if proc else (bool(pid) and pid_alive(pid))


def running(store: Store) -> dict | None:
    """The job marked running, after checking its process is really alive (a dead one is marked failed)."""
    job = store.one("SELECT * FROM jobs WHERE status='running' ORDER BY id DESC LIMIT 1")
    return job if job and _still_alive(store, job) else None


def job_running(store: Store, job_id: int) -> bool:
    """Whether this one job is running: its row says so and its process lives (a dead one is marked failed)."""
    job = store.one("SELECT id, status, pid FROM jobs WHERE id=?", [job_id])
    return bool(job and job["status"] == "running" and _still_alive(store, job))


def _still_alive(store: Store, job: dict) -> bool:
    alive = process_alive(job["id"], job.get("pid"))
    if not alive:
        fresh = store.one("SELECT status FROM jobs WHERE id=?", [job["id"]])
        if fresh and fresh["status"] == "running":
            store.update("jobs", "id", job["id"], {"status": "failed", "finished_at": now(), "exit_code": -1})
    return alive


def prune_live(p: Project) -> None:
    """Keep only the newest live recordings (`live.keep_sessions` in project.yaml, default 15)."""
    root = p.state / "live"
    if not root.exists():
        return
    keep = int(p.cfg.get("live", {}).get("keep_sessions", KEEP_LIVE_SESSIONS))
    dirs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs[keep:]:
        shutil.rmtree(d, ignore_errors=True)


def child_env(extra: dict[str, str]) -> dict[str, str]:
    """The environment for a stage process: ours minus the API's sign-in secrets, plus the live-view settings."""
    kept = {k: v for k, v in os.environ.items() if not k.startswith(API_SECRET_PREFIXES)}
    return {**kept, **extra}


def spawn(p: Project, s: Store, args: list[str], label: str, headed: bool = False, shots: bool | None = None) -> int:
    """Start `python -m agentqa <args>` for the project as a tracked job; returns the job id."""
    if running(s):
        raise Busy("A stage is already running for this project.")
    log_path = p.state / "logs" / f"{label}-{now().replace(':', '')}.log"
    job_id = s.insert("jobs", {"stage": label, "status": "running", "started_at": now(), "log_path": str(log_path)})
    lc = p.cfg.get("live", {})
    live_dir = p.state / "live" / f"job-{job_id}-{label}"
    extra = {"PYTHONIOENCODING": "utf-8", "AGENTQA_LIVE_DIR": str(live_dir), "AGENTQA_LIVE_FROM_UI": "1",
             "AGENTQA_LIVE_SHOTS": "1" if (lc.get("screenshots", True) if shots is None else shots) else "0",
             "AGENTQA_LIVE_QUALITY": str(lc.get("quality", 50))}
    if headed:
        extra.update({"AGENTQA_HEADED": "1", "AGENTQA_SLOWMO": str(lc.get("slowmo_ms", 400))})
    env = child_env(extra)
    prune_live(p)
    live_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as fh:
        proc = subprocess.Popen([sys.executable, "-u", "-m", "agentqa", *args, "-p", str(p.root), "--job-id", str(job_id)],
                                cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT, env=env)
    PROCS[job_id] = proc
    s.update("jobs", "id", job_id, {"pid": proc.pid})
    return job_id
