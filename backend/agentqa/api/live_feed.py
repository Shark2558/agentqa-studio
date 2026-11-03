"""One live feed for both transports (Server-Sent Events and WebSocket, M1.3), and the cap on open live streams.

`live_feed` reads the run's event files every half second in a worker thread (file reads and the store are blocking
I/O and must never run on the event loop), yields batches of at most MAX_BATCH events, and ends with one `end` item
saying why: "finished" (the run is over and nothing new remains), "idle" (an hour without a word), "signed-out" (the
sign-in expired) or "gone" (the run's folder was pruned). A passing read or database error on Windows / Drive (a file
held open by another process, a locked database) is logged and tried again at the next poll."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from agentqa.config import Project
from agentqa.orchestrator import NotFound, live

log = logging.getLogger("agentqa.api.live")
POLL_S = 0.5
IDLE_LIMIT_S = 3600           # a stream never outlives a run by more than this
AUTH_CHECK_S = 60             # how often a long stream re-checks that its sign-in has not expired
MAX_BATCH = 2000              # events per message, so one big read never becomes one huge frame


async def live_feed(p: Project, d: Path, session: str, cursor: str = "", signed_in: Callable[[], bool] = lambda: True,
                    *, poll_s: float = POLL_S, idle_limit_s: float = IDLE_LIMIT_S, auth_check_s: float = AUTH_CHECK_S,
                    max_batch: int = MAX_BATCH) -> AsyncIterator[dict]:
    """{"type": "live", "events", "cursor"} batches, then one {"type": "end", "cursor", "reason"}."""
    token, last_news, checked = cursor, time.monotonic(), time.monotonic()
    while True:
        before = token
        events, token, gone = await _read(d, token)
        for item in _batches(events, before, token, max_batch):
            yield item
        if events:
            last_news = time.monotonic()
        reason = "gone" if gone else (None if events else await _why_stop(p, session, last_news, idle_limit_s))
        if reason:
            if reason != "gone":                              # the run's last words, written as it ended
                before = token
                last, token, _ = await _read(d, token)
                for item in _batches(last, before, token, max_batch):
                    yield item
            yield {"type": "end", "cursor": token, "reason": reason}
            return
        if not events:
            await asyncio.sleep(poll_s)
        if time.monotonic() - checked >= auth_check_s:
            checked = time.monotonic()
            if not signed_in():
                yield {"type": "end", "cursor": token, "reason": "signed-out"}
                return


def _batches(events: list[dict], before: str, after: str, max_batch: int) -> list[dict]:
    """Messages of at most `max_batch` events. Only the last carries the new cursor: a browser that reconnects after
    an earlier one re-reads from `before` (and drops what it already has) instead of skipping the rest."""
    chunks = [events[i:i + max_batch] for i in range(0, len(events), max_batch)]
    return [{"type": "live", "events": chunk, "cursor": after if n == len(chunks) - 1 else before}
            for n, chunk in enumerate(chunks)]


async def _read(d: Path, token: str) -> tuple[list[dict], str, bool]:
    """New events and the next cursor, in a worker thread; `gone` when the run's folder no longer exists."""
    try:
        events, following = await asyncio.to_thread(live.read_events, d, token)
    except FileNotFoundError:
        return [], token, True
    except OSError as exc:                                    # held open elsewhere for a moment: try again next poll
        log.warning("live read of %s failed, retrying: %s", d.name, type(exc).__name__)
        return [], token, False
    return events, following, False


async def _why_stop(p: Project, session: str, last_news: float, idle_limit_s: float) -> str | None:
    if time.monotonic() - last_news > idle_limit_s:
        return "idle"
    try:
        running = await asyncio.to_thread(live.is_running, p, session)
    except (NotFound, FileNotFoundError):
        return "gone"
    except (OSError, sqlite3.Error) as exc:                   # a locked database or a busy file: ask again next poll
        log.warning("could not tell whether %s is running, retrying: %s", session, type(exc).__name__)
        return None
    return None if running else "finished"


class StreamSlots:
    """Open live streams (SSE and WebSocket together) per client address and in total. A stream holds a `Lease`
    from opening to closing; the lease is released once, whichever way the stream ends."""

    def __init__(self, per_client: int, total: int):
        self.per_client, self.total = per_client, total
        self._open: dict[str, int] = {}
        self._count = 0
        self._lock = threading.Lock()

    def lease(self, key: str) -> "Lease | None":
        with self._lock:
            if self._count >= self.total or self._open.get(key, 0) >= self.per_client:
                return None
            self._open[key] = self._open.get(key, 0) + 1
            self._count += 1
        return Lease(self, key)

    def open_count(self, key: str | None = None) -> int:
        with self._lock:
            return self._count if key is None else self._open.get(key, 0)

    def _release(self, key: str) -> None:
        with self._lock:
            left = self._open.get(key, 0) - 1
            if left > 0:
                self._open[key] = left
            else:
                self._open.pop(key, None)
            self._count = max(0, self._count - 1)


class Lease:
    def __init__(self, slots: StreamSlots, key: str):
        self._slots, self._key = slots, key
        self._released = False
        self._lock = threading.Lock()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._slots._release(self._key)
