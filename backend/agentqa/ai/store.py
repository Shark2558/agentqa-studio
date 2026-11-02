"""Installation-wide AI settings: provider keys (encrypted), the routing policy, key health and an audit log.

ai.vault  encrypted JSON: {"keys": [...], "policy": {...}}; a key's secret never leaves this file except to
          call its provider, and the dashboard only ever shows it masked
ai.db     SQLite: key_state (health, cooldowns, models found) and ai_events (every failure, switch and
          success summary), with any key text scrubbed out before it is written
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

DEFAULT_POLICY = {
    "order": ["gemini", "openai", "anthropic", "azure_openai", "deepseek", "groq", "mistral", "openrouter",
              "openai_compatible", "ollama"],
    "provider_fallback": True,       # when every key of a provider fails, try the next provider in `order`
    "attempts_per_key": 2,           # tries per key on timeouts, outages and broken answers
    "timeout_s": 60,
    "backoff_s": 1.0,                # wait between tries on the same key (doubles each try)
    "cooldown_s": {"rate_limit": 60, "quota": 3600, "unavailable": 120, "timeout": 60, "connection": 120,
                   "bad_output": 30},
    "send_screenshots": False,       # images go to providers only when this is on
    "redact": True,                  # mask mobile numbers, emails and 12-digit numbers before sending
}
_LOCK = threading.Lock()
SECRET_PATTERNS = [re.compile(p) for p in (r"sk-[A-Za-z0-9_\-]{12,}", r"AIza[0-9A-Za-z_\-]{20,}", r"gsk_[A-Za-z0-9]{20,}",
                                            r"sk-ant-[A-Za-z0-9_\-]{12,}", r"sk-or-[A-Za-z0-9_\-]{12,}")]


def agentqa_home() -> Path:
    if os.environ.get("AGENTQA_HOME"):
        return Path(os.environ["AGENTQA_HOME"])
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / "AgentQA"
    return Path.home() / ".agentqa"


def mask_key(k: str | None) -> str:
    k = str(k or "")
    return "(none)" if not k else (k[:4] + "…" + k[-4:]) if len(k) > 12 else "•" * len(k)


class AIStore:
    def __init__(self, home: Path | None = None):
        self.home = Path(home or agentqa_home())
        self.home.mkdir(parents=True, exist_ok=True)
        self.vault = self.home / "ai.vault"
        self.db_path = self.home / "ai.db"
        with self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS key_state (key_id TEXT PRIMARY KEY, state TEXT, cooldown_until REAL,
                consecutive INTEGER DEFAULT 0, last_error TEXT, last_kind TEXT, last_ok TEXT, last_ms INTEGER,
                models TEXT, requests INTEGER DEFAULT 0, failures INTEGER DEFAULT 0, rate_limits INTEGER DEFAULT 0,
                dead_model TEXT);
            CREATE TABLE IF NOT EXISTS ai_events (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, key_id TEXT,
                provider TEXT, label TEXT, model TEXT, task TEXT, outcome TEXT, status INTEGER, detail TEXT,
                switched_to TEXT, ms INTEGER);""")

    # ---- encrypted settings ------------------------------------------------------------------
    def _fernet(self) -> Fernet:
        from agentqa.vault import _key
        return Fernet(_key())

    def load(self) -> dict:
        data = {}
        if self.vault.exists():
            try:
                data = json.loads(self._fernet().decrypt(json.loads(self.vault.read_text(encoding="utf-8"))["data"].encode()))
            except (InvalidToken, ValueError, KeyError) as exc:
                raise RuntimeError(f"{self.vault} was encrypted with another key; re-enter the AI keys") from exc
        data.setdefault("keys", [])
        pol = {**DEFAULT_POLICY, **(data.get("policy") or {})}
        pol["cooldown_s"] = {**DEFAULT_POLICY["cooldown_s"], **((data.get("policy") or {}).get("cooldown_s") or {})}
        data["policy"] = pol
        return data

    def save(self, data: dict) -> None:
        with _LOCK:
            tmp = self.vault.with_suffix(".tmp")
            tmp.write_text(json.dumps({"version": 1, "data": self._fernet().encrypt(json.dumps(data).encode()).decode()}),
                           encoding="utf-8")
            os.replace(tmp, self.vault)

    def keys(self) -> list[dict]:
        return sorted(self.load()["keys"], key=lambda k: (k.get("priority", 100), k.get("label", "")))

    def policy(self) -> dict:
        return self.load()["policy"]

    def upsert_key(self, values: dict) -> str:
        data = self.load()
        kid = values.get("id") or uuid.uuid4().hex[:10]
        cur = next((k for k in data["keys"] if k["id"] == kid), None)
        if cur is None:
            cur = {"id": kid, "status": "active", "priority": 10, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            data["keys"].append(cur)
        for f, v in values.items():
            if f == "key" and not v:
                continue                                  # an empty key box keeps the stored key
            if f != "id":
                cur[f] = v
        self.save(data)
        if values.get("key") or values.get("model") or values.get("base_url"):
            self.reset_state(kid)                         # edited: give it a fresh chance
        return kid

    def delete_key(self, kid: str) -> None:
        data = self.load()
        data["keys"] = [k for k in data["keys"] if k["id"] != kid]
        self.save(data)
        with self._db() as db:
            db.execute("DELETE FROM key_state WHERE key_id=?", [kid])

    def set_policy(self, policy: dict) -> None:
        data = self.load()
        data["policy"] = {**data["policy"], **policy}
        self.save(data)

    def public_keys(self) -> list[dict]:
        """For the dashboard: everything but the secret."""
        states = {s["key_id"]: s for s in self.states()}
        out = []
        for k in self.keys():
            row = {f: v for f, v in k.items() if f != "key"}
            row["masked"] = mask_key(k.get("key"))
            row["state"] = states.get(k["id"], {})
            out.append(row)
        return out

    # ---- health ---------------------------------------------------------------------------
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def states(self) -> list[dict]:
        with self._db() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM key_state")]
        for r in rows:
            r["models"] = json.loads(r["models"] or "[]")
        return rows

    def state(self, kid: str) -> dict:
        return next((s for s in self.states() if s["key_id"] == kid), {"key_id": kid, "state": "untested", "consecutive": 0})

    def update_state(self, kid: str, **fields) -> None:
        if "models" in fields:
            fields["models"] = json.dumps(fields["models"])
        with _LOCK, self._db() as db:
            db.execute("INSERT OR IGNORE INTO key_state (key_id, state) VALUES (?, 'untested')", [kid])
            for f, v in fields.items():
                if f in ("requests", "failures", "rate_limits") and isinstance(v, str) and v == "+1":
                    db.execute(f"UPDATE key_state SET {f} = COALESCE({f}, 0) + 1 WHERE key_id=?", [kid])
                else:
                    db.execute(f"UPDATE key_state SET {f}=? WHERE key_id=?", [v, kid])

    def reset_state(self, kid: str) -> None:
        self.update_state(kid, state="untested", cooldown_until=None, consecutive=0, last_error=None, dead_model=None)

    # ---- audit log ----------------------------------------------------------------------------
    def scrub(self, text: str | None) -> str:
        t = str(text or "")
        for k in self.load()["keys"]:
            if k.get("key") and len(k["key"]) >= 6:
                t = t.replace(k["key"], mask_key(k["key"]))
        for p in SECRET_PATTERNS:
            t = p.sub(lambda m: mask_key(m.group(0)), t)
        return t[:500]

    def event(self, key: dict | None, outcome: str, detail: str = "", task: str = "", model: str = "",
              status: int | None = None, switched_to: str = "", ms: int | None = None) -> None:
        with _LOCK, self._db() as db:
            db.execute("INSERT INTO ai_events (at, key_id, provider, label, model, task, outcome, status, detail, switched_to, ms) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       [time.strftime("%Y-%m-%dT%H:%M:%S"), (key or {}).get("id"), (key or {}).get("provider"),
                        (key or {}).get("label"), model, task, outcome, status, self.scrub(detail), switched_to, ms])

    def events(self, limit: int = 100) -> list[dict]:
        with self._db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM ai_events ORDER BY id DESC LIMIT ?", [limit])]

    def counts(self) -> dict:
        with self._db() as db:
            rows = db.execute("SELECT outcome, COUNT(*) n FROM ai_events WHERE at >= ? GROUP BY outcome",
                              [time.strftime("%Y-%m-%dT00:00:00")]).fetchall()
        return {r["outcome"]: r["n"] for r in rows}
