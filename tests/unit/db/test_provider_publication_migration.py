from pathlib import Path

from picotoopet_core.db.database import Database


REQUIRED_PUBLICATION_COLUMNS = {
    "publication_candidate_id", "commit_candidate_id", "session_id", "handoff_id", "status", "repo_url",
    "repository_slug", "base_ref", "base_commit", "commit_sha", "change_set_digest", "remote_ref",
    "remote_branch", "approval_id", "idempotency_key", "pr_title_digest", "pr_body_digest", "pr_number",
    "pr_url", "pr_head_sha", "validation_json", "failure_code", "created_at", "updated_at", "finished_at",
    "preview_json",
}


def test_migration_ten_creates_publication_candidate_table_idempotently(tmp_path: Path) -> None:
    database = Database(tmp_path / "publication.db")
    database.open(); database.apply_migrations(); database.apply_migrations()
    columns = {row["name"] for row in database.fetchall("PRAGMA table_info(provider_publication_candidates)")}
    assert REQUIRED_PUBLICATION_COLUMNS <= columns
    # Schema retention gate      Migration 10 remains once and later migrations advance through 22.
    assert database.scalar("SELECT MAX(version) FROM schema_migrations") == 22
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 10") == 1
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 11") == 1
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 12") == 1
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 13") == 1
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 14") == 1
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 15") == 1
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 16") == 1
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 17") == 1
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 18") == 1
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 19") == 1
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 20") == 1
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 21") == 1
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 22") == 1
    database.close()


def test_migration_ten_preserves_existing_commit_candidate_table(tmp_path: Path) -> None:
    database = Database(tmp_path / "preserve.db")
    database.open(); database.apply_migrations()
    assert database.scalar("SELECT COUNT(*) FROM provider_commit_candidates") == 0
    assert database.scalar("SELECT COUNT(*) FROM provider_publication_candidates") == 0
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 22
    database.close()
