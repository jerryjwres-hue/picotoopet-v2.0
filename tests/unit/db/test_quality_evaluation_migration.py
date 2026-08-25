from __future__ import annotations

from pathlib import Path

from picotoopet_core.db.database import Database


EVALUATION_TABLES = {
    "quality_evaluation_snapshots",
    "quality_evaluation_snapshot_members",
    "quality_evaluation_runs",
    "quality_evaluation_metrics",
    "quality_improvement_candidates",
    "quality_improvement_candidate_reviews",
}


def test_schema_16_adds_quality_evaluation_tables_after_schema_15(tmp_path: Path) -> None:
    database = Database(tmp_path / "core.db")
    database.open()
    try:
        database.apply_migrations()
        tables = {
            row[0]
            for row in database.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        # Current schema gate      Migration history advances through browser-scan schema 23.
        assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 23
        # 23.1 schema gate         Migration 16 itself remains registered exactly once.
        assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version=16") == 1
        # 22.1 preservation gate   Existing Deep-AI / learning facts must remain present.
        assert "deep_ai_escalation_jobs" in tables
        assert "deep_ai_learning_events" in tables
        assert "deep_ai_learning_details" in tables
        # 23.1 persistence gate    Evaluation facts are normalized durable tables.
        assert EVALUATION_TABLES <= tables

        database.apply_migrations()
        assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 23
    finally:
        database.close()


def test_schema_16_snapshot_member_and_candidate_identity_constraints(tmp_path: Path) -> None:
    database = Database(tmp_path / "constraints.db")
    database.open()
    try:
        database.apply_migrations()
        # Identity gate            Snapshot/run/candidate natural identities must be unique.
        snapshot_indexes = {
            row["name"]
            for row in database.fetchall("PRAGMA index_list(quality_evaluation_snapshots)")
        }
        candidate_indexes = {
            row["name"]
            for row in database.fetchall("PRAGMA index_list(quality_improvement_candidates)")
        }
        assert snapshot_indexes
        assert candidate_indexes
        # Referential gate         Every 23.1 table remains under SQLite foreign-key enforcement.
        assert database.scalar("PRAGMA foreign_keys") == 1
    finally:
        database.close()
