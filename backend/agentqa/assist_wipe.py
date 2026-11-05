"""Nothing a person types into the help box stays readable (M1.4 decision 2).

The project's database may sit in a folder synced to the cloud. So a typed take-over command keeps only its length
once the agent has typed it (or once it can no longer run), a secret answer (a one-time code) becomes "[given]" once
the agent has read it, and a question's screenshot is deleted when the question ends. Overwriting is not enough on
its own: `secure_delete` zeroes the space the old value took, and a checkpoint empties the write-ahead log that still
holds it. A checkpoint that a reader holds up waits at most CHECKPOINT_WAIT_MS; the once-a-minute sweep always
checkpoints again, so the log is emptied then."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from agentqa.store import Store
from agentqa.util import warn

GIVEN = "[given]"                         # what a secret answer reads once the agent has it
ANSWER_KEEP_S = 60                        # a secret answer no agent read (its run crashed) is wiped after this
COMMAND_KEEP_S = 60                       # an agent runs a command within a second: one still waiting is stale
CHECKPOINT_WAIT_MS = 1000
STORE_WAIT_MS = 30_000                    # the store's own busy timeout (Store opens with timeout=30)
SHOT_NAME = re.compile(r"(\d{1,10})-\d{1,10}\.jpg")      # a question's screenshot, as assist_screen.Shooter names it


def _since(seconds: int) -> str:
    return (datetime.now() - timedelta(seconds=seconds)).isoformat(timespec="seconds")


def atomic(store: Store, sql: str, params: list) -> sqlite3.Cursor:
    """One write whose condition is read under the write lock (BEGIN IMMEDIATE): two requests at once cannot both
    pass it (the first answer wins; at most 20 commands wait)."""
    conn = store.conn
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(sql, params)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return cur


def overwrite(store: Store, table: str, row_id: int, changes: dict) -> None:
    """Replace a row's values with `secure_delete` on, so the old text is zeroed in the file (checkpoint after)."""
    store.conn.execute("PRAGMA secure_delete=ON")
    store.update(table, "id", row_id, changes)


def checkpoint(store: Store) -> bool:
    """Empty the write-ahead log into the file; True when it is empty. A reader can hold it up: then this gives up
    after CHECKPOINT_WAIT_MS rather than stall the agent, and the next sweep tries again."""
    conn = store.conn
    try:
        conn.execute(f"PRAGMA busy_timeout={CHECKPOINT_WAIT_MS}")
        busy = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
    except sqlite3.Error as exc:
        busy = exc.__class__.__name__
    finally:
        conn.execute(f"PRAGMA busy_timeout={STORE_WAIT_MS}")
    if busy:
        warn(f"the help box's database log could not be emptied yet ({busy}); the next sweep empties it")
    return not busy


def kept(cmd: dict, secret: bool | None = None) -> dict:
    """A typed command as it is kept once typed: its length, never its text."""
    chars = len(str(cmd.get("text") or "")) if "text" in cmd else int(cmd.get("chars") or 0)
    return {"kind": "type", "chars": chars, "secret": bool(cmd.get("secret") if secret is None else secret),
            "replace": bool(cmd.get("replace"))}


def _json(column: str, path: str) -> str:
    """`column`'s value at `path`, or NULL for text that is not JSON (SQL; the names are literals from this module)."""
    return f"CASE WHEN json_valid({column}) THEN json_extract({column}, '{path}') END"


def forget_typed(store: Store, aid: int | None = None) -> int:
    """Wipe the text of every typed command that has run, can no longer run (its take-over ended) or has waited longer
    than COMMAND_KEEP_S (its agent is gone); one that never ran is marked "dropped". Returns how many."""
    where = (f"{_json('c.cmd', '$.kind')} = 'type' AND {_json('c.cmd', '$.text')} IS NOT NULL AND (c.status != 'new' "
             "OR a.status IS NULL OR a.status != 'pending' OR c.at < ?)") + (" AND c.assist_id = ?" if aid else "")
    rows = store.all(f"SELECT c.id, c.cmd, c.status FROM assist_cmds c LEFT JOIN assist a ON a.id = c.assist_id "
                     f"WHERE {where}", [_since(COMMAND_KEEP_S), *([aid] if aid else [])])
    for r in rows:
        changes = {"cmd": kept(r["cmd"] if isinstance(r["cmd"], dict) else {})}
        overwrite(store, "assist_cmds", r["id"], {**changes, **({"status": "dropped"} if r["status"] == "new" else {})})
    if rows:
        checkpoint(store)
    return len(rows)


def forget_unread_answers(store: Store) -> int:
    """A secret answer that no agent read (its run crashed, or it came as the question ran out of time) is wiped once
    it is ANSWER_KEEP_S old, whatever the question's status. Returns how many."""
    rows = store.all(f"SELECT id, answer FROM assist WHERE status != 'pending' AND {_json('detail', '$.secret')} "
                     f"AND {_json('answer', '$.text')} IS NOT NULL AND {_json('answer', '$.text')} != ? "
                     "AND COALESCE(answered_at, at) < ?", [GIVEN, _since(ANSWER_KEEP_S)])
    for r in rows:
        overwrite(store, "assist", r["id"], {"answer": {**(r["answer"] if isinstance(r["answer"], dict) else {}),
                                                        "text": GIVEN}})
    if rows:
        checkpoint(store)
    return len(rows)


def forget_screens(store: Store, folder: Path) -> int:
    """Delete the screenshots of questions that no longer wait (a typed code may show in a plain box)."""
    waiting = {r["id"] for r in store.all("SELECT id FROM assist WHERE status='pending'")}
    gone = 0
    for f in folder.glob("*.jpg") if folder.is_dir() else []:
        m = SHOT_NAME.fullmatch(f.name)
        if m and int(m.group(1)) not in waiting:
            try:
                f.unlink()
                gone += 1
            except OSError as exc:              # a download may hold it open on Windows: the next sweep tries again
                warn(f"could not delete the old help-box screenshot {f.name} ({exc.__class__.__name__})")
    return gone


def sweep(store: Store, shots: Path | None = None) -> None:
    """Everything a crashed or finished run left readable; always ends with a checkpoint (it is cheap when the log is
    already empty, and it finishes a checkpoint an earlier wipe had to give up)."""
    forget_typed(store)
    forget_unread_answers(store)
    if shots is not None:
        forget_screens(store, shots)
    checkpoint(store)
