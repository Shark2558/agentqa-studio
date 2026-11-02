"""SQLite store for everything the agents produce. One file per project."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS requirements (
    id TEXT PRIMARY KEY, seq INTEGER, section TEXT, text TEXT, kind TEXT,
    priority TEXT, roles TEXT, ambiguity TEXT, source_file TEXT);
CREATE TABLE IF NOT EXISTS rules (
    id TEXT PRIMARY KEY, req_id TEXT, kind TEXT, field TEXT, value TEXT,
    roles TEXT, target TEXT, source TEXT, confidence REAL, status TEXT,
    status_note TEXT, matched TEXT, decided_value TEXT);
CREATE TABLE IF NOT EXISTS screens (
    id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, path TEXT, url TEXT,
    status INTEGER, title TEXT, headings TEXT, links TEXT, forms TEXT,
    buttons TEXT, a11y TEXT, console TEXT, load_ms INTEGER, pattern TEXT,
    server_error INTEGER DEFAULT 0, final_url TEXT);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT, rule_id TEXT, req_id TEXT, kind TEXT,
    question TEXT, options TEXT, proposed TEXT, priority TEXT, status TEXT,
    answer TEXT, answer_value TEXT, answered_at TEXT, context TEXT);
CREATE TABLE IF NOT EXISTS plan (
    id INTEGER PRIMARY KEY CHECK (id = 1), approved INTEGER, approved_at TEXT,
    summary TEXT);
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY, key TEXT, seq INTEGER, type TEXT, title TEXT, role TEXT, path TEXT,
    params TEXT, rule_ids TEXT, req_ids TEXT, priority TEXT, oracle_source TEXT,
    status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, total INTEGER,
    passed INTEGER, failed INTEGER, errors INTEGER, skipped INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS results (
    run_id TEXT, case_id TEXT, outcome TEXT, duration REAL, message TEXT,
    evidence TEXT, nodeid TEXT, category TEXT);
CREATE TABLE IF NOT EXISTS defects (
    id TEXT PRIMARY KEY, seq INTEGER, run_id TEXT, case_ids TEXT, signature TEXT,
    title TEXT, severity TEXT, priority TEXT, role TEXT, url TEXT, steps TEXT,
    expected TEXT, actual TEXT, evidence TEXT, rule_ids TEXT, req_ids TEXT,
    status TEXT, created_at TEXT, notes TEXT, external_key TEXT);
CREATE TABLE IF NOT EXISTS heals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, run_id TEXT, kind TEXT,
    old TEXT, new TEXT, reason TEXT, status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, sig TEXT, severity TEXT, title TEXT,
    roles TEXT, path TEXT, url TEXT, steps TEXT, expected TEXT, detail TEXT, evidence TEXT,
    rule_id TEXT, req_id TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS endpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, method TEXT, path TEXT, pattern TEXT,
    status INTEGER, content_type TEXT, keys TEXT, shape TEXT, initiator TEXT, ms INTEGER,
    source TEXT, documented INTEGER);
CREATE TABLE IF NOT EXISTS visual (
    key TEXT PRIMARY KEY, role TEXT, path TEXT, status TEXT, diff_ratio REAL, baseline TEXT,
    current TEXT, diff TEXT, run_id TEXT, case_id TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT, who TEXT, text TEXT, data TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS manual_cases (
    id TEXT PRIMARY KEY, title TEXT, role TEXT, steps TEXT, expected TEXT, converted TEXT,
    coverage REAL, status TEXT, source_file TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, stage TEXT, status TEXT, started_at TEXT,
    finished_at TEXT, log_path TEXT, pid INTEGER, exit_code INTEGER);
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, system TEXT, defect_id TEXT, external_key TEXT,
    action TEXT, detail TEXT, ok INTEGER);
CREATE TABLE IF NOT EXISTS zap_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, plugin_id TEXT, alert TEXT, risk TEXT, confidence TEXT,
    url TEXT, method TEXT, param TEXT, evidence TEXT, description TEXT, solution TEXT, reference TEXT,
    cwe TEXT, role TEXT, sig TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS assist (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, kind TEXT, role TEXT, agent TEXT, question TEXT,
    detail TEXT, status TEXT, answer TEXT, answered_at TEXT);
CREATE TABLE IF NOT EXISTS assist_cmds (
    id INTEGER PRIMARY KEY AUTOINCREMENT, assist_id INTEGER, at TEXT, cmd TEXT, status TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS journeys (
    id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, from_path TEXT, action TEXT, target TEXT, kind TEXT,
    to_path TEXT, title TEXT, detail TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS auth_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, role TEXT, app TEXT, method TEXT, otp_source TEXT, result TEXT,
    detail TEXT, agent TEXT, seconds REAL);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, kind TEXT, size INTEGER, pages INTEGER, segments INTEGER,
    status TEXT, detail TEXT, read_at TEXT);
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, doc TEXT, ref TEXT, kind TEXT, text TEXT, req_ids TEXT,
    disposition TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS stage_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, pipeline TEXT, stage TEXT, status TEXT, started_at TEXT, finished_at TEXT,
    outputs TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, agent TEXT, object TEXT, object_id TEXT, change TEXT,
    justification TEXT, by TEXT);
"""

JSON_COLUMNS = {
    "roles", "ambiguity", "value", "matched", "decided_value", "headings", "links",
    "forms", "buttons", "a11y", "console", "options", "summary", "params",
    "rule_ids", "req_ids", "evidence", "case_ids", "old", "new", "context",
    "keys", "data", "converted", "external_sync", "detail", "answer", "std", "outputs", "cmd", "result",
}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


WAL_RETRIES = 100          # 100 x 50 ms: five seconds for another opener to finish switching a new database to WAL
WAL_RETRY_WAIT_S = 0.05


def _enable_wal(conn: sqlite3.Connection) -> None:
    """Switch the database to WAL. SQLite answers 'database is locked' instead of waiting (the busy timeout does not
    apply to a journal-mode change) when another connection is in the middle of the same switch on a brand-new file,
    so the switch is retried briefly. A database already in WAL mode returns at once."""
    for _ in range(WAL_RETRIES):
        try:
            mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower():
                raise
        else:
            if str(mode).lower() == "wal":       # SQLite may also answer with the old mode instead of raising
                return
        time.sleep(WAL_RETRY_WAIT_S)
    raise sqlite3.OperationalError(f"could not switch {conn} to WAL: database stayed locked")


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.conn = sqlite3.connect(str(self.path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        _enable_wal(self.conn)
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    MIGRATIONS = [("runs", "changes", "INTEGER"), ("defects", "external_system", "TEXT"), ("defects", "external_url", "TEXT"),
                  ("defects", "external_status", "TEXT"), ("defects", "external_sync", "TEXT"),
                  ("runs", "blocked", "INTEGER"), ("runs", "not_run", "INTEGER"), ("runs", "scope", "TEXT"),
                  ("requirements", "std", "TEXT"), ("requirements", "disposition", "TEXT"),
                  ("requirements", "disposition_note", "TEXT"), ("requirements", "source_ref", "TEXT"),
                  ("results", "started_at", "TEXT")]

    def _migrate(self) -> None:
        """Add columns introduced by later versions to an existing database."""
        for table, column, kind in self.MIGRATIONS:
            cols = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                try:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
                except sqlite3.OperationalError as exc:
                    if "duplicate column" not in str(exc):
                        raise           # another process (the dashboard, a job) added it at the same moment

    # ---- generic helpers ----------------------------------------------------
    @staticmethod
    def _enc(key: str, value: Any) -> Any:
        if key in JSON_COLUMNS and value is not None and not isinstance(value, str):
            return json.dumps(value, ensure_ascii=False)
        return value

    @staticmethod
    def _dec(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        out = dict(row)
        for key, value in out.items():
            if key in JSON_COLUMNS and isinstance(value, str):
                try:
                    out[key] = json.loads(value)
                except json.JSONDecodeError:
                    pass
        return out

    def insert(self, table: str, row: dict, replace: bool = False) -> int:
        cols = list(row.keys())
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        sql = f"{verb} INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})"
        cur = self.conn.execute(sql, [self._enc(c, row[c]) for c in cols])
        self.conn.commit()
        return cur.lastrowid

    def update(self, table: str, key: str, key_value: Any, changes: dict) -> None:
        if not changes:
            return
        sets = ",".join(f"{c}=?" for c in changes)
        self.conn.execute(f"UPDATE {table} SET {sets} WHERE {key}=?",
                          [self._enc(c, v) for c, v in changes.items()] + [key_value])
        self.conn.commit()

    def all(self, sql: str, params: Iterable = ()) -> list[dict]:
        return [self._dec(r) for r in self.conn.execute(sql, list(params)).fetchall()]

    def one(self, sql: str, params: Iterable = ()) -> dict | None:
        return self._dec(self.conn.execute(sql, list(params)).fetchone())

    def scalar(self, sql: str, params: Iterable = ()) -> Any:
        row = self.conn.execute(sql, list(params)).fetchone()
        return row[0] if row else None

    def exec(self, sql: str, params: Iterable = ()) -> None:
        self.conn.execute(sql, list(params))
        self.conn.commit()

    def clear(self, *tables: str) -> None:
        for t in tables:
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()

    # ---- meta -------------------------------------------------------------
    def set_meta(self, key: str, value: Any) -> None:
        self.insert("meta", {"key": key, "value": json.dumps(value)}, replace=True)

    def get_meta(self, key: str, default: Any = None) -> Any:
        v = self.scalar("SELECT value FROM meta WHERE key=?", [key])
        return json.loads(v) if v is not None else default

    def close(self) -> None:
        self.conn.close()
