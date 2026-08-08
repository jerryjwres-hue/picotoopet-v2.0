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
    "handoffs",
    "returns",
    "broker_sessions",
    "provider_usage_confirmations",
    "provider_sessions",
    "provider_return_artifacts",
    "provider_review_decisions",
    "provider_adoption_candidates",
    "provider_commit_candidates",
    "workflow_runs",
    "workflow_steps",
    "workflow_step_dependencies",
    "workflow_checkpoints",
    "artifact_provenance",
    "artifact_links",
    "capability_registrations",
    "quality_decisions",
    "workflow_handoff_continuations",
}

REQUIRED_HANDOFF_COLUMNS = {
    "handoff_id",
    "template_id",
    "title",
    "objective_summary",
    "status",
    "request_digest",
    "package_digest",
    "manifest_json",
    "preview_json",
    "approval_id",
    "prepare_idempotency_key",
    "approval_idempotency_key",
    "created_at",
    "updated_at",
    "expires_at",
}


def test_database_applies_required_pragmas_and_schema(tmp_path: Path) -> None:
    """数据库必须启用耐久参数并幂等创建当前完整表结构。"""

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
    task_columns = {row["name"] for row in database.fetchall("PRAGMA table_info(tasks)")}
    handoff_columns = {
        row["name"] for row in database.fetchall("PRAGMA table_info(handoffs)")
    }
    assert REQUIRED_TABLES <= tables
    assert "cloud_policy" in task_columns
    assert REQUIRED_HANDOFF_COLUMNS <= handoff_columns
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 9
    database.close()


def test_migration_three_repairs_partially_registered_handoff_table(tmp_path: Path) -> None:
    """表已存在但 migration 记录缺失时必须安全登记，而不是重复破坏数据。"""

    database = Database(tmp_path / "partial.db")
    database.open()
    database.execute(
        "CREATE TABLE handoffs ("
        "handoff_id TEXT PRIMARY KEY, template_id TEXT NOT NULL, title TEXT NOT NULL, "
        "objective_summary TEXT NOT NULL, status TEXT NOT NULL, request_digest TEXT NOT NULL, "
        "package_digest TEXT NOT NULL, manifest_json TEXT NOT NULL, preview_json TEXT NOT NULL, "
        "approval_id TEXT, prepare_idempotency_key TEXT NOT NULL UNIQUE, "
        "approval_idempotency_key TEXT UNIQUE, created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, expires_at TEXT NOT NULL)"
    )
    database.apply_migrations()

    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 3") == 1
    assert REQUIRED_HANDOFF_COLUMNS <= {
        row["name"] for row in database.fetchall("PRAGMA table_info(handoffs)")
    }
    database.close()
