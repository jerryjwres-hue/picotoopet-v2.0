import sqlite3
from pathlib import Path

import pytest

from picotoopet_core.db.database import Database


REQUIRED_TABLES = {
    "schema_migrations",
    "projects",
    "artifacts",
    "tasks",
    "task_dependencies",
    "task_attempts",
    "task_events",
    "approvals",
    "results",
    "audit_events",
    "idempotency_keys",
    "device_pairings",
    "service_health",
    "event_outbox",
    "executor_leases",
    "executor_artifacts",
    "executor_thumbnails",
    "executor_redos",
    "executor_qc_picks",
    "production_episodes",
    "owner_production_hold",
}


def test_database_applies_required_pragmas_and_schema(tmp_path: Path) -> None:
    """数据库必须启用耐久参数并创建完整 Phase 1 表结构。"""

    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    database.apply_migrations()

    assert database.scalar("PRAGMA journal_mode") == "wal"
    assert database.scalar("PRAGMA foreign_keys") == 1
    tables = {
        row[0]
        for row in database.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert REQUIRED_TABLES <= tables
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 4
    # 新建的旧版兼容项目默认没有激活 Owner 保护；仅迁移不会自行授权/禁用 GPU。
    assert database.scalar("SELECT COUNT(*) FROM owner_production_hold") == 0
    database.close()

def test_newer_24_migration_database_is_not_modified(tmp_path: Path) -> None:
    """防止旧 Core 将现有 24 版迁移表误认为本分支的第 4 版迁移。"""
    db_path = tmp_path / "existing-24.db"
    with sqlite3.connect(db_path) as raw:
        raw.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        raw.execute("CREATE TABLE tasks (task_id TEXT PRIMARY KEY)")
        raw.execute("INSERT INTO tasks(task_id) VALUES ('preserve-existing-task')")
        raw.executemany(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 'historical')",
            ((version,) for version in range(1, 25)),
        )
    database = Database(db_path)
    database.open()
    try:
        with pytest.raises(RuntimeError, match="UNSUPPORTED_EXISTING_DATABASE_SCHEMA"):
            database.apply_migrations()
        assert database.scalar("SELECT MAX(version) FROM schema_migrations") == 24
        assert database.scalar("SELECT COUNT(*) FROM tasks") == 1
        assert database.scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='owner_production_hold'"
        ) == 0
    finally:
        database.close()


def test_overlapping_version_4_without_owner_hold_stops(tmp_path: Path) -> None:
    """旧系统也可能使用 migration=4；不能用相同数字假装 Owner 安全表存在。"""
    db_path = tmp_path / "incompatible-v4.db"
    with sqlite3.connect(db_path) as raw:
        raw.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        raw.execute("INSERT INTO schema_migrations VALUES (4, 'historical')")
        raw.execute("CREATE TABLE legacy_data (id INTEGER PRIMARY KEY)")
        raw.execute("INSERT INTO legacy_data VALUES (123)")
    database = Database(db_path)
    database.open()
    try:
        with pytest.raises(RuntimeError, match="INCOMPATIBLE_MIGRATION_004"):
            database.apply_migrations()
        assert database.scalar("SELECT COUNT(*) FROM legacy_data") == 1
        assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 1
    finally:
        database.close()
