"""The change log as the gates write and read it: who (the signed-in person), what, and why (FR-ACC-3).

Rows go into the store's `change_log` table (`by` holds who, `justification` holds why). M2.1 adds `user_id`."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol

from agentqa.store import Store, now

WHY_MAX = 500
CHANGE_MAX = 1000
PAGE_MAX = 200
PAGE_DEFAULT = 50
DOWNLOAD_QUIET_S = 60          # the same download by the same person is logged once a minute
COLUMNS = "id, at, agent, object, object_id, change, justification, by"


class Person(Protocol):
    @property
    def email(self) -> str: ...

    @property
    def role(self) -> str: ...


def who(user: Person) -> str:
    return f"{user.email} ({user.role})"


def clean_why(why: str | None) -> str:
    """A reason as stored: one line (a newline cannot start a fake entry in a note), at most WHY_MAX characters."""
    return " ".join((why or "").split())[:WHY_MAX]


def record(store: Store, obj: str, object_id: str, change: str, why: str | None, by: str) -> int:
    """One row for a person's decision; returns its id."""
    return store.insert("change_log", {"at": now(), "agent": "person", "object": obj, "object_id": str(object_id)[:200],
                                       "change": change[:CHANGE_MAX], "justification": clean_why(why), "by": by})


def record_download(store: Store, file: str, change: str, by: str) -> int | None:
    """A download, unless the same person downloaded the same thing in the last minute (a reload or a burst of
    clicks must not push the decisions off the first page)."""
    since = (datetime.now() - timedelta(seconds=DOWNLOAD_QUIET_S)).isoformat(timespec="seconds")
    if store.scalar("SELECT COUNT(*) FROM change_log WHERE object='export' AND object_id=? AND change=? AND by=? "
                    "AND at >= ?", [file, change, by, since]):
        return None
    return record(store, "export", file, change, "", by)


def _item(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "at": row["at"], "agent": row["agent"], "object": row["object"],
            "object_id": row["object_id"], "change": row["change"], "why": row["justification"] or "", "by": row["by"]}


def page(store: Store, limit: int = PAGE_DEFAULT, before: int | None = None) -> dict[str, Any]:
    """Newest first; `next_before` is the id to pass as `before` for the next page, or None at the end."""
    limit = max(1, min(int(limit), PAGE_MAX))
    where, params = ("WHERE id < ?", [before]) if before else ("", [])
    rows = store.all(f"SELECT {COLUMNS} FROM change_log {where} ORDER BY id DESC LIMIT ?", [*params, limit + 1])
    items = [_item(r) for r in rows[:limit]]
    return {"items": items, "next_before": items[-1]["id"] if len(rows) > limit else None}


def last(store: Store, obj: str, change_prefix: str) -> dict[str, Any] | None:
    """The newest row for `obj` whose change starts with `change_prefix` (e.g. who approved the plan last)."""
    row = store.one(f"SELECT {COLUMNS} FROM change_log WHERE object=? AND substr(change, 1, ?)=? ORDER BY id DESC LIMIT 1",
                    [obj, len(change_prefix), change_prefix])
    return _item(row) if row else None
