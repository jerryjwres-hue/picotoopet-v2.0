"""Ensure shared SQLite connection queries keep the existing RLock while fetching."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

from picotoopet_core.db.database import Database


def _prove_atomic_fetch(method: str) -> None:
    entered = Event()
    release = Event()
    writer_completed = Event()

    class BlockingCursor:
        def fetchone(self) -> tuple[int]:
            # ── Test holds this SELECT cursor open while a writer competes.
            entered.set()
            assert release.wait(5), "reader fetch timed out"
            return (1,)

        def fetchall(self) -> list[tuple[int]]:
            # ── Same cursor lifecycle contract for multirow reads.
            entered.set()
            assert release.wait(5), "reader fetch timed out"
            return [(1,)]

    cursor = BlockingCursor()

    class FakeConnection:
        def execute(self, sql: str, parameters: tuple[object, ...]) -> BlockingCursor:
            # ── A writer must never execute before the reader exits fetch.
            if sql.startswith("UPDATE"):
                writer_completed.set()
            return cursor

    database = Database("ignored-by-fake-connection.db")
    database._connection = FakeConnection()  # type: ignore[assignment]

    with ThreadPoolExecutor(max_workers=2) as executor:
        reader = executor.submit(getattr(database, method), "SELECT value FROM t")
        writer = None
        try:
            assert entered.wait(5), "reader never entered cursor fetch"
            writer = executor.submit(database.execute, "UPDATE t SET value = 2")
            assert not writer_completed.wait(0.2), "writer interleaved before cursor fetch ended"
        finally:
            release.set()
        assert reader.result(timeout=5) == ((1,) if method == "fetchone" else [(1,)])
        assert writer is not None
        writer.result(timeout=5)
        assert writer_completed.is_set()


def test_fetchone_holds_shared_connection_lock_until_cursor_consumed() -> None:
    _prove_atomic_fetch("fetchone")


def test_fetchall_holds_shared_connection_lock_until_cursor_consumed() -> None:
    _prove_atomic_fetch("fetchall")
