from pathlib import Path

from picotoopet_core.db.database import Database


REQUIRED_TABLES = {
    "schema_migrations", "projects", "artifacts", "tasks", "task_dependencies", "task_attempts",
    "task_events", "approvals", "results", "audit_events", "idempotency_keys", "device_pairings",
    "service_health", "event_outbox", "handoffs", "returns", "broker_sessions",
    "provider_usage_confirmations", "provider_sessions", "provider_return_artifacts",
    "provider_review_decisions", "provider_adoption_candidates", "provider_commit_candidates",
    "provider_publication_candidates", "workflow_runs", "workflow_steps", "workflow_step_dependencies",
    "workflow_checkpoints", "artifact_provenance", "artifact_links", "capability_registrations",
    "quality_decisions", "workflow_handoff_continuations", "business_work_packages", "business_artifacts",
    "business_upload_sessions", "business_upload_chunks", "local_intelligence_runs",
    "local_intelligence_chunks", "business_result_packages", "deep_ai_handoffs", "creative_jobs",
    "creative_job_sources", "creative_source_findings", "creative_stage_runs", "creative_packages",
    "creative_deep_ai_handoffs", "production_jobs", "production_tasks", "production_attempts",
    "production_packages", "business_pipeline_runs", "business_return_packages",
    "deep_ai_escalation_jobs", "deep_ai_attempts", "deep_ai_learning_events", "deep_ai_learning_details",
    "quality_evaluation_snapshots", "quality_evaluation_snapshot_members", "quality_evaluation_runs",
    "quality_evaluation_metrics", "quality_improvement_candidates",
    "quality_improvement_candidate_reviews", "quality_shadow_runs", "quality_shadow_arm_metrics",
    "quality_shadow_reviews", "quality_promotions", "quality_promotion_approval_requests",
    "quality_promotion_decisions", "quality_promotion_rollbacks", "autonomous_goals",
    "autonomous_products", "autonomous_evidence", "autonomous_legacy_imports",
    "autonomous_browser_captures",
}

REQUIRED_HANDOFF_COLUMNS = {
    "handoff_id", "template_id", "title", "objective_summary", "status", "request_digest",
    "package_digest", "manifest_json", "preview_json", "approval_id", "prepare_idempotency_key",
    "approval_idempotency_key", "created_at", "updated_at", "expires_at",
}


def test_database_applies_required_pragmas_and_schema(tmp_path: Path) -> None:
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
    handoff_columns = {row["name"] for row in database.fetchall("PRAGMA table_info(handoffs)")}
    assert REQUIRED_TABLES <= tables
    assert "cloud_policy" in task_columns
    assert REQUIRED_HANDOFF_COLUMNS <= handoff_columns
    # Schema gate              Migration history is cumulative and exact through schema 20.
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 20
    database.close()


def test_migration_three_repairs_partially_registered_handoff_table(tmp_path: Path) -> None:
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
