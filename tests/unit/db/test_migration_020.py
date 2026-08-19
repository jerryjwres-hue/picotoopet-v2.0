from __future__ import annotations

from pathlib import Path

from picotoopet_core.db.database import Database


def test_migration_020_adds_canonical_connected_evidence_tables(tmp_path: Path) -> None:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    try:
        assert database.scalar("SELECT MAX(version) FROM schema_migrations") == 21
        tables = {
            row["name"]
            for row in database.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        }
        assert "autonomous_evidence" in tables
        assert "autonomous_legacy_imports" in tables
        assert "autonomous_browser_captures" in tables

        evidence_columns = {
            row["name"] for row in database.fetchall("PRAGMA table_info(autonomous_evidence)")
        }
        assert {
            "evidence_id",
            "product_key",
            "source",
            "source_url",
            "source_entity_id",
            "text_value",
            "raw_hash",
            "trust_level",
            "captured_at",
            "origin",
            "external_ref_type",
            "external_ref_id",
            "idempotency_key",
            "provenance_json",
        }.issubset(evidence_columns)
    finally:
        database.close()
