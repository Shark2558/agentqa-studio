"""Store: several Store objects may be created on the same brand-new database at once (an agent thread and the
dashboard both open it). Switching a new database to WAL is not covered by SQLite's busy timeout, so the second
opener used to fail with 'database is locked'."""
from __future__ import annotations

import threading
from contextlib import closing

from agentqa.store import Store

OPENERS = 6
JOIN_TIMEOUT_S = 30


def test_concurrent_store_creation_on_a_fresh_database_never_fails(tmp_path):
    # Arrange
    path = tmp_path / "fresh.db"
    errors: list[Exception] = []
    gate = threading.Barrier(OPENERS)

    def open_store() -> None:
        try:
            gate.wait(timeout=5)                 # every thread opens at the same instant
            Store(path).conn.close()
        except Exception as e:                   # the test records whatever went wrong
            errors.append(e)

    # Act
    threads = [threading.Thread(target=open_store) for _ in range(OPENERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=JOIN_TIMEOUT_S)

    # Assert
    assert not any(t.is_alive() for t in threads), "an opener hung instead of finishing"
    assert not errors, f"opening the store concurrently raised: {errors!r}"
    with closing(Store(path).conn) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
