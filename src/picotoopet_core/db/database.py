"""线程安全的 SQLite 连接与迁移入口。"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

from .migration_009 import MIGRATION_009
from .migration_010 import MIGRATION_010
from .migration_011 import MIGRATION_011
from .migration_012 import MIGRATION_012
from .migration_013 import MIGRATION_013
from .migration_014 import MIGRATION_014
from .migration_015 import MIGRATION_015
from .migration_016 import MIGRATION_016
from .migration_017 import MIGRATION_017
from .migration_018 import MIGRATION_018
from .migration_019 import MIGRATION_019
from .migration_020 import MIGRATION_020
from .migration_021 import MIGRATION_021
from .migration_022 import MIGRATION_022
from .migration_023 import MIGRATION_023
from .schema import (
    MIGRATION_001,
    MIGRATION_002,
    MIGRATION_003,
    MIGRATION_004,
    MIGRATION_005,
    MIGRATION_006,
    MIGRATION_007,
    MIGRATION_008,
)
from .task_visibility_schema import TASK_VISIBILITY_SCHEMA


class Database:
    """Mac Core SQLite 数据库。"""

    def __init__(self, path: Path | str) -> None:
        self.path        = Path(path).expanduser().resolve()
        self._connection: sqlite3.Connection | None = None
        self._lock       = threading.RLock()

    @property
    def connection(self) -> sqlite3.Connection:
        """返回已打开连接。"""

        if self._connection is None:
            raise RuntimeError("数据库尚未打开。")
        return self._connection

    def open(self) -> None:
        """打开数据库并应用耐久参数。"""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self.path,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._connection.execute("PRAGMA synchronous=FULL")

    def close(self) -> None:
        """关闭连接。"""

        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """以 IMMEDIATE 事务执行一组写入。"""

        with self._lock:
            connection = self.connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def apply_migrations(self) -> None:
        """幂等应用数据库迁移，并兼容部分升级状态。"""

        with self.transaction() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            migration_001_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 1"
            ).fetchone()
            if migration_001_exists is None:
                connection.executescript(MIGRATION_001)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (1, datetime.now(UTC).isoformat()),
                )

            migration_002_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 2"
            ).fetchone()
            if migration_002_exists is None:
                task_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
                }
                if "cloud_policy" not in task_columns:
                    connection.executescript(MIGRATION_002)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (2, datetime.now(UTC).isoformat()),
                )

            migration_003_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 3"
            ).fetchone()
            if migration_003_exists is None:
                connection.executescript(MIGRATION_003)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (3, datetime.now(UTC).isoformat()),
                )

            migration_004_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 4"
            ).fetchone()
            if migration_004_exists is None:
                connection.executescript(MIGRATION_004)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (4, datetime.now(UTC).isoformat()),
                )

            migration_005_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 5"
            ).fetchone()
            if migration_005_exists is None:
                connection.executescript(MIGRATION_005)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (5, datetime.now(UTC).isoformat()),
                )

            migration_006_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 6"
            ).fetchone()
            if migration_006_exists is None:
                connection.executescript(MIGRATION_006)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (6, datetime.now(UTC).isoformat()),
                )

            migration_007_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 7"
            ).fetchone()
            if migration_007_exists is None:
                connection.executescript(MIGRATION_007)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (7, datetime.now(UTC).isoformat()),
                )

            migration_008_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 8"
            ).fetchone()
            if migration_008_exists is None:
                connection.executescript(MIGRATION_008)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (8, datetime.now(UTC).isoformat()),
                )

            migration_009_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 9"
            ).fetchone()
            if migration_009_exists is None:
                connection.executescript(MIGRATION_009)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (9, datetime.now(UTC).isoformat()),
                )

            migration_010_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 10"
            ).fetchone()
            if migration_010_exists is None:
                connection.executescript(MIGRATION_010)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (10, datetime.now(UTC).isoformat()),
                )

            migration_011_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 11"
            ).fetchone()
            if migration_011_exists is None:
                connection.executescript(MIGRATION_011)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (11, datetime.now(UTC).isoformat()),
                )

            migration_012_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 12"
            ).fetchone()
            if migration_012_exists is None:
                connection.executescript(MIGRATION_012)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (12, datetime.now(UTC).isoformat()),
                )

            migration_013_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 13"
            ).fetchone()
            if migration_013_exists is None:
                # ── 2.3.20.1 local ComfyUI production facts ─────────────────
                connection.executescript(MIGRATION_013)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (13, datetime.now(UTC).isoformat()),
                )

            migration_014_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 14"
            ).fetchone()
            if migration_014_exists is None:
                # ── 2.3.21.1 end-to-end business pipeline facts ─────────────
                connection.executescript(MIGRATION_014)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (14, datetime.now(UTC).isoformat()),
                )

            migration_015_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 15"
            ).fetchone()
            if migration_015_exists is None:
                # ── 2.3.22.1 paid-AI escalation + quality-learning facts ────
                connection.executescript(MIGRATION_015)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (15, datetime.now(UTC).isoformat()),
                )

            migration_016_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 16"
            ).fetchone()
            if migration_016_exists is None:
                # ── 2.3.23.1 deterministic offline evaluation facts ─────────
                connection.executescript(MIGRATION_016)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (16, datetime.now(UTC).isoformat()),
                )

            migration_017_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 17"
            ).fetchone()
            if migration_017_exists is None:
                # ── 2.3.24.1 deterministic controlled-shadow facts ──────────
                connection.executescript(MIGRATION_017)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (17, datetime.now(UTC).isoformat()),
                )

            migration_018_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 18"
            ).fetchone()
            if migration_018_exists is None:
                # ── 2.3.25.1 controlled Promotion / rollback facts ──────────
                connection.executescript(MIGRATION_018)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (18, datetime.now(UTC).isoformat()),
                )

            migration_019_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 19"
            ).fetchone()
            if migration_019_exists is None:
                # ── Autonomous Goal metadata extends existing workflows without duplicating queue facts. ──
                connection.executescript(MIGRATION_019)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (19, datetime.now(UTC).isoformat()),
                )

            migration_020_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 20"
            ).fetchone()
            if migration_020_exists is None:
                # ── Connected evidence becomes Core-owned facts; legacy databases stay read-only. ──
                connection.executescript(MIGRATION_020)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (20, datetime.now(UTC).isoformat()),
                )

            migration_021_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 21"
            ).fetchone()
            if migration_021_exists is None:
                # ── Frugal coding escalation decisions remain immutable Core-owned audit facts. ──
                connection.executescript(MIGRATION_021)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (21, datetime.now(UTC).isoformat()),
                )

            migration_022_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 22"
            ).fetchone()
            if migration_022_exists is None:
                # ── Superpower v1.0 progress is append-only Core truth, never a UI-only estimate. ──
                connection.executescript(MIGRATION_022)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (22, datetime.now(UTC).isoformat()),
                )

            migration_023_exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 23"
            ).fetchone()
            if migration_023_exists is None:
                # ── Each Browser Bridge scan stays auditable; canonical evidence remains globally deduped. ──
                connection.executescript(MIGRATION_023)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (23, datetime.now(UTC).isoformat()),
                )

            # ── 删除/恢复仍是操作员列表元数据；累计 Core Schema 现在推进到 23。 ──
            connection.executescript(TASK_VISIBILITY_SCHEMA)

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> sqlite3.Cursor:
        """执行单条 SQL。"""

        with self._lock:
            return self.connection.execute(sql, tuple(parameters))

    def fetchone(self, sql: str, parameters: Sequence[Any] = ()) -> sqlite3.Row | None:
        """读取单行。"""

        return self.execute(sql, parameters).fetchone()

    def fetchall(self, sql: str, parameters: Sequence[Any] = ()) -> list[sqlite3.Row]:
        """读取全部行。"""

        return list(self.execute(sql, parameters).fetchall())

    def scalar(self, sql: str, parameters: Sequence[Any] = ()) -> Any:
        """读取首行首列。"""

        row = self.fetchone(sql, parameters)
        return None if row is None else row[0]
