from __future__ import annotations

import threading
from pathlib import Path

import pytest

from picotoopet_core.db.database import Database


class _BlockingCursor:
    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        self.entered = entered
        self.release = release

    def _wait(self):
        self.entered.set()
        assert self.release.wait(timeout=2)
        return (1,)

    def fetchone(self):
        return self._wait()

    def fetchall(self):
        return [self._wait()]


class _Connection:
    def __init__(
        self,
        *,
        entered: threading.Event,
        release: threading.Event,
        transaction_began: threading.Event,
    ) -> None:
        self.entered = entered
        self.release = release
        self.transaction_began = transaction_began

    def execute(self, sql: str, parameters=()):  # type: ignore[no-untyped-def]
        if sql == "SELECT 1":
            return _BlockingCursor(self.entered, self.release)
        if sql == "BEGIN IMMEDIATE":
            self.transaction_began.set()
        return self

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


@pytest.mark.parametrize("reader", ["fetchone", "fetchall", "scalar"])
def test_reads_hold_connection_lock_until_cursor_is_consumed(
    tmp_path: Path,
    reader: str,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    transaction_began = threading.Event()
    database = Database(tmp_path / "core.db")
    database._connection = _Connection(  # type: ignore[assignment]
        entered=entered,
        release=release,
        transaction_began=transaction_began,
    )

    def read() -> None:
        getattr(database, reader)("SELECT 1")

    def write() -> None:
        with database.transaction():
            pass

    reader_thread = threading.Thread(target=read)
    writer_thread = threading.Thread(target=write)
    reader_thread.start()
    assert entered.wait(timeout=1)

    writer_thread.start()
    assert transaction_began.wait(timeout=0.1) is False

    release.set()
    reader_thread.join(timeout=2)
    writer_thread.join(timeout=2)

    assert reader_thread.is_alive() is False
    assert writer_thread.is_alive() is False
    assert transaction_began.is_set()
