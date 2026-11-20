from pathlib import Path

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
