from __future__ import annotations

from pathlib import Path

from picotoopet_core.db.database import Database


SHADOW_TABLES = {
    "quality_shadow_runs",
    "quality_shadow_arm_metrics",
    "quality_shadow_reviews",
}


def test_schema_17_adds_shadow_tables_after_schema_16(tmp_path: Path) -> None:
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
        # Current schema gate      Migration history advances through schema 18.
        assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 18
        # 24.1 schema gate         Migration 17 itself remains registered exactly once.
        assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version=17") == 1
        # 23.1 preservation gate   Offline evaluation and candidate facts remain available.
        assert "quality_evaluation_snapshots" in tables
        assert "quality_evaluation_runs" in tables
        assert "quality_improvement_candidates" in tables
        # 24.1 persistence gate    Shadow validation facts are normalized durable tables.
        assert SHADOW_TABLES <= tables

        database.apply_migrations()
        assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 18
    finally:
        database.close()


def test_schema_17_shadow_identity_is_unique_and_foreign_keys_stay_enabled(tmp_path: Path) -> None:
    database = Database(tmp_path / "constraints.db")
    database.open()
    try:
        database.apply_migrations()
        run_indexes = {
            row["name"]
            for row in database.fetchall("PRAGMA index_list(quality_shadow_runs)")
        }
        review_indexes = {
            row["name"]
            for row in database.fetchall("PRAGMA index_list(quality_shadow_reviews)")
        }
        # Identity gate            One candidate has at most one shadow run; review keys are idempotent.
        assert run_indexes
        assert review_indexes
        # Referential gate         Schema 17 facts remain under SQLite foreign-key enforcement.
        assert database.scalar("PRAGMA foreign_keys") == 1
    finally:
        database.close()
