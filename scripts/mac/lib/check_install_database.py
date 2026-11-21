#!/usr/bin/env python3
"""Read-only SQLite 1–24 compatibility gate and verified online backup for Mac upgrades."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

SUPPORTED_SCHEMA = 24


def _readonly(database: Path) -> sqlite3.Connection:
    """始终以 read-only 连接原始 Core DB，WAL 活动时也不直接复制数据库文件。"""

    uri = "file:" + quote(str(database.resolve()), safe="/") + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=15)


def inspect(connection: sqlite3.Connection) -> tuple[int, int, int]:
    """按旧版 2.3 的迁移表及标志性表验证兼容性，拒绝同号异构版本。"""

    connection.execute("PRAGMA query_only=ON")
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise ValueError("SQLITE_INTEGRITY_FAILED")

    # 迁移 4 在 2.3 中创建 returns，而旧的 V3.1 候选把 4 用于 Owner HOLD。
    # 检查实际表结构，而不是仅比较 schema_migrations 最大编号。
    versions = [
        row[0] for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    ]
    if not versions or any(type(v) is not int for v in versions):
        raise ValueError("UNKNOWN_SCHEMA_MIGRATIONS")
    maximum = versions[-1]
    if maximum > SUPPORTED_SCHEMA or versions != list(range(1, maximum + 1)):
        raise ValueError("UNSUPPORTED_SCHEMA_MIGRATIONS")

    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    required = {"schema_migrations", "tasks", "approvals"}
    if maximum >= 3:
        required.add("handoffs")
    if maximum >= 4:
        required.add("returns")
    if maximum >= 24:
        required.add("creative_goal_source_sets")
    if not required.issubset(tables):
        raise ValueError("INCOMPATIBLE_MIGRATION_TABLE_SIGNATURE")

    task_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
    }
    approval_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(approvals)").fetchall()
    }
    if not {"task_id", "status"}.issubset(task_columns) or "approval_id" not in approval_columns:
        raise ValueError("INCOMPATIBLE_CORE_TABLE_COLUMNS")

    tasks = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    approvals = connection.execute("SELECT COUNT(*) FROM approvals").fetchone()[0]
    return maximum, tasks, approvals


def verify_backup(database: Path, original: tuple[int, int, int]) -> None:
    """对备份文件进行独立只读重开与任务/审批计数验证。"""

    with _readonly(database) as check:
        if inspect(check) != original:
            raise ValueError("BACKUP_CONTENT_MISMATCH")


def check_database(database: Path, backup_dir: Path | None) -> None:
    """预检无副作用；仅显式 backup 阶段才写独立快照。"""

    if not database.exists():
        print("DATABASE=NEW")
        return
    if database.is_symlink() or not database.is_file() or database.stat().st_size == 0:
        raise ValueError("UNSAFE_EXISTING_DATABASE")

    with _readonly(database) as source:
        summary = inspect(source)
        print(f"SCHEMA=COMPATIBLE_{summary[0]} TASKS={summary[1]} APPROVALS={summary[2]}")
        if backup_dir is None:
            return

        # 先完整备份并验证，再容许安装器替换 Core 指针或 LaunchAgent。
        # 只备份用户已有数据，不修改 schema_migrations、审批或生产门禁。
        old_umask = os.umask(0o077)
        snapshot: Path | None = None
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            snapshot = backup_dir / (
                f"pre-v31-compat-schema{summary[0]}-{stamp}-{os.getpid()}.db"
            )
            with sqlite3.connect(snapshot) as destination:
                source.backup(destination)
            verify_backup(snapshot, summary)
            print(f"DATABASE_BACKUP=PASS FILE={snapshot}")
        except Exception:
            if snapshot is not None:
                snapshot.unlink(missing_ok=True)
            raise
        finally:
            os.umask(old_umask)


def main() -> int:
    parser = argparse.ArgumentParser(description="PicotooPet 2.3 SQLite compatibility gate")
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--backup-dir", type=Path)
    arguments = parser.parse_args()
    try:
        check_database(arguments.database, arguments.backup_dir)
    except (OSError, sqlite3.Error, ValueError) as exc:
        # 不打印敏感数据、完整 SQL、认证信息或数据库行内容。
        code = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f"STOP=DATABASE_COMPATIBILITY:{code}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
