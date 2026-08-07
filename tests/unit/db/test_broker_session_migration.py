from pathlib import Path

from picotoopet_core.db.database import Database


REQUIRED_BROKER_COLUMNS = {
    "session_id",
    "handoff_id",
    "status",
    "provider",
    "timeout_seconds",
    "request_digest",
    "package_digest",
    "return_id",
    "event_count",
    "sandbox_digest",
    "failure_code",
    "idempotency_key",
    "created_at",
    "updated_at",
    "finished_at",
}


def test_migration_five_creates_broker_session_fact_table_idempotently(
    tmp_path: Path,
) -> None:
    """Migration 5 必须幂等创建 Broker Session 安全事实表。"""

    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    database.apply_migrations()

    tables = {
        row[0]
        for row in database.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    broker_columns = {
        row["name"] for row in database.fetchall("PRAGMA table_info(broker_sessions)")
    }

    assert "broker_sessions" in tables
    assert REQUIRED_BROKER_COLUMNS <= broker_columns
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 8
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 5") == 1
    database.close()


def test_migration_five_preserves_handoff_and_return_rows(tmp_path: Path) -> None:
    """Broker Session 迁移不得改写已存在的 Handoff 与 Return 事实。"""

    database = Database(tmp_path / "preserve.db")
    database.open()
    database.apply_migrations()

    assert database.scalar("SELECT COUNT(*) FROM handoffs") == 0
    assert database.scalar("SELECT COUNT(*) FROM returns") == 0
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 8
    database.close()
