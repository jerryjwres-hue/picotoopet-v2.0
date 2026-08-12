from pathlib import Path

from picotoopet_core.db.database import Database


REQUIRED_ARTIFACT_COLUMNS = {"return_id", "session_id", "handoff_id", "base_commit", "change_set_digest", "review_diff_digest", "changed_file_count", "payload_bytes", "artifact_status", "created_at", "preview_json"}
REQUIRED_DECISION_COLUMNS = {"decision_id", "session_id", "return_id", "decision", "change_set_digest", "idempotency_key", "created_at", "preview_json"}
REQUIRED_CANDIDATE_COLUMNS = {"candidate_id", "session_id", "return_id", "status", "base_commit", "change_set_digest", "changed_file_count", "validation_json", "failure_code", "idempotency_key", "created_at", "updated_at", "finished_at", "preview_json"}


def _columns(database: Database, table: str) -> set[str]:
    return {row["name"] for row in database.fetchall(f"PRAGMA table_info({table})")}


def test_migration_seven_creates_review_and_adoption_tables_idempotently(tmp_path: Path) -> None:
    database = Database(tmp_path / "review.db")
    database.open(); database.apply_migrations(); database.apply_migrations()
    assert REQUIRED_ARTIFACT_COLUMNS <= _columns(database, "provider_return_artifacts")
    assert REQUIRED_DECISION_COLUMNS <= _columns(database, "provider_review_decisions")
    assert REQUIRED_CANDIDATE_COLUMNS <= _columns(database, "provider_adoption_candidates")
    # Schema retention gate      Migration 7 remains exactly once inside cumulative schema 18.
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 18
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 7") == 1
    database.close()


def test_migration_seven_preserves_existing_provider_session_rows(tmp_path: Path) -> None:
    database = Database(tmp_path / "preserve.db")
    database.open(); database.apply_migrations()
    now = "2026-08-07T15:20:00+00:00"; expires = "2026-08-07T16:20:00+00:00"
    database.execute(
        "INSERT INTO handoffs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?)",
        ("handoff-review-existing", "picotoopet-repo-maintenance-codex-v1", "existing review", "existing objective", "approved", "a" * 64, "b" * 64, "{}", "{}", "handoff-review-key", now, now, expires),
    )
    database.execute(
        "INSERT INTO provider_sessions (session_id, handoff_id, provider, status, request_digest, package_digest, budget_json, idempotency_key, created_at, updated_at, preview_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("11111111-1111-1111-1111-111111111111", "handoff-review-existing", "codex", "ready_for_review", "a" * 64, "b" * 64, "{}", "provider-review-existing", now, now, "{}"),
    )
    before = database.fetchone("SELECT handoff_id, status, request_digest, package_digest FROM provider_sessions WHERE session_id = ?", ("11111111-1111-1111-1111-111111111111",))
    database.apply_migrations()
    after = database.fetchone("SELECT handoff_id, status, request_digest, package_digest FROM provider_sessions WHERE session_id = ?", ("11111111-1111-1111-1111-111111111111",))
    assert before is not None and after is not None
    assert tuple(after) == tuple(before)
    assert database.scalar("SELECT COUNT(*) FROM provider_sessions") == 1
    database.close()
