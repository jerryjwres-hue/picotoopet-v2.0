from pathlib import Path

from picotoopet_core.db.database import Database


REQUIRED_COMMIT_COLUMNS = {
    "commit_candidate_id", "adoption_candidate_id", "session_id", "return_id", "status", "base_commit",
    "change_set_digest", "tree_sha", "commit_sha", "local_ref", "approval_id", "idempotency_key",
    "validation_json", "failure_code", "author_time_utc", "created_at", "updated_at", "finished_at",
    "preview_json",
}


def test_migration_eight_creates_commit_candidate_table_idempotently(tmp_path: Path) -> None:
    database = Database(tmp_path / "commit.db")
    database.open(); database.apply_migrations(); database.apply_migrations()
    columns = {row["name"] for row in database.fetchall("PRAGMA table_info(provider_commit_candidates)")}
    assert REQUIRED_COMMIT_COLUMNS <= columns
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 15
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 8") == 1
    database.close()


def test_migration_eight_preserves_existing_adoption_rows(tmp_path: Path) -> None:
    database = Database(tmp_path / "preserve.db")
    database.open(); database.apply_migrations()
    assert database.scalar("SELECT COUNT(*) FROM provider_adoption_candidates") == 0
    assert database.scalar("SELECT COUNT(*) FROM provider_commit_candidates") == 0
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 15
    database.close()
