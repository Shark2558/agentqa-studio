"""A small per-address token bucket for every endpoint (ECC security rule); Redis replaces it in the cloud edition."""
from __future__ import annotations

import threading
import time

MAX_CLIENTS = 10_000          # addresses remembered at once; the least recently seen is forgotten beyond this


class RateLimiter:
    def __init__(self, per_minute: int, max_clients: int = MAX_CLIENTS):
        self.capacity = float(per_minute)
        self.refill_per_s = per_minute / 60.0
        self.max_clients = max_clients
        self._buckets: dict[str, tuple[float, float]] = {}      # key -> (tokens, last refill time), insertion = recency
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        with self._lock:
            tokens, last = self._buckets.pop(key, (self.capacity, time.time()))
            now = time.time()
            tokens = min(self.capacity, tokens + (now - last) * self.refill_per_s)
            allowed = tokens >= 1
            self._buckets[key] = (tokens - 1 if allowed else tokens, now)   # re-inserted: now the most recent
            while len(self._buckets) > self.max_clients:
                self._buckets.pop(next(iter(self._buckets)))
            return allowed
