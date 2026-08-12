from __future__ import annotations

from pathlib import Path

from picotoopet_core.db.database import Database


PROMOTION_TABLES = {
    "quality_promotions",
    "quality_promotion_approval_requests",
    "quality_promotion_decisions",
    "quality_promotion_rollbacks",
}


def test_schema_18_adds_promotion_tables_after_schema_17(tmp_path: Path) -> None:
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
        # 25.1 schema gate         Migration 18 is registered exactly once after Shadow schema 17.
        assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 18
        assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version=18") == 1
        # 24.1 preservation gate   Shadow evidence remains durable and unchanged.
        assert "quality_shadow_runs" in tables
        assert "quality_shadow_reviews" in tables
        # 25.1 persistence gate    Promotion governance is normalized into bounded fact tables.
        assert PROMOTION_TABLES <= tables

        database.apply_migrations()
        assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 18
    finally:
        database.close()


def test_schema_18_has_one_active_per_slot_and_idempotent_decision_indexes(tmp_path: Path) -> None:
    database = Database(tmp_path / "constraints.db")
    database.open()
    try:
        database.apply_migrations()
        promotion_indexes = {
            row["name"]
            for row in database.fetchall("PRAGMA index_list(quality_promotions)")
        }
        decision_indexes = {
            row["name"]
            for row in database.fetchall("PRAGMA index_list(quality_promotion_decisions)")
        }
        # Registry gate            Schema must enforce slot/version and a partial one-Active invariant.
        assert "ux_quality_promotions_slot_version" in promotion_indexes
        assert "ux_quality_promotions_active_slot" in promotion_indexes
        # Decision gate            Replayed human decisions cannot append duplicate side effects.
        assert "ux_quality_promotion_decisions_idempotency" in decision_indexes
        assert database.scalar("PRAGMA foreign_keys") == 1
    finally:
        database.close()
