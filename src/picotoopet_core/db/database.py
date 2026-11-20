"""线程安全的 SQLite 连接与迁移入口。"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schema import MIGRATION_001, MIGRATION_002, MIGRATION_003, MIGRATION_004


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
        """幂等应用 Phase 1 数据库迁移。"""

        with self.transaction() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = 1"
            ).fetchone()
            if exists is None:
                for statement in MIGRATION_001.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (1, datetime.now(UTC).isoformat()),
                )
            for version, statements in ((2, MIGRATION_002), (3, MIGRATION_003), (4, MIGRATION_004)):
                if connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
                ).fetchone() is None:
                    for statement in statements:
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (version, datetime.now(UTC).isoformat()),
                    )

    def owner_gpu_hold(self, *, owner_credentials_configured: bool) -> bool:
        """激活并持久化 Owner 保护状态；凭据被删除后也不能自动回退为 legacy GPU。

        这是独立于 Owner token 的永久入口锁；只有受信任的未来生产准入
        可以精确授权某个冻结任务，本标记本身永不授予 GPU 权限。
        """
        with self.transaction() as connection:
            if owner_credentials_configured:
                connection.execute(
                    "INSERT OR IGNORE INTO owner_production_hold(hold_id, activated_at) "
                    "VALUES (1, ?)",
                    (datetime.now(UTC).isoformat(),),
                )
            row = connection.execute(
                "SELECT hold_id FROM owner_production_hold WHERE hold_id = 1"
            ).fetchone()
            return row is not None

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
