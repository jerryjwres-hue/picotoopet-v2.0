from __future__ import annotations

from pathlib import Path

from picotoopet_core.db.database import Database


def test_schema_23_makes_scan_manifest_key_primary_and_capture_content_id_repeatable(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "core.db")
    database.open()
    try:
        database.apply_migrations()
        assert database.scalar("SELECT MAX(version) FROM schema_migrations") == 23

        columns = {
            row["name"]: row
            for row in database.fetchall("PRAGMA table_info(autonomous_browser_captures)")
        }
        assert columns["idempotency_key"]["pk"] == 1
        assert columns["capture_id"]["pk"] == 0

        indexes = {
            row["name"]: row
            for row in database.fetchall("PRAGMA index_list(autonomous_browser_captures)")
        }
        assert indexes["idx_autonomous_browser_capture_packet"]["unique"] == 0
        assert indexes["idx_autonomous_browser_capture_content_id"]["unique"] == 0
    finally:
        database.close()
