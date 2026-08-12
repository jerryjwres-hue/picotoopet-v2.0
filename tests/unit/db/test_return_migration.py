from pathlib import Path

from picotoopet_core.db.database import Database


REQUIRED_RETURN_COLUMNS = {"return_id", "handoff_id", "status", "provider", "request_digest", "package_digest", "manifest_digest", "changed_file_count", "event_count", "validation_checks_json", "preview_json", "quarantine_code", "idempotency_key", "created_at", "updated_at"}


def test_migration_four_creates_return_fact_table_idempotently(tmp_path: Path) -> None:
    database = Database(tmp_path / "core.db")
    database.open(); database.apply_migrations(); database.apply_migrations()
    tables = {row[0] for row in database.fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    return_columns = {row["name"] for row in database.fetchall("PRAGMA table_info(returns)")}
    assert "returns" in tables
    assert REQUIRED_RETURN_COLUMNS <= return_columns
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 15
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 4") == 1
    database.close()


def test_migration_four_repairs_partially_registered_return_table(tmp_path: Path) -> None:
    database = Database(tmp_path / "partial.db")
    database.open()
    database.execute("CREATE TABLE returns (return_id TEXT PRIMARY KEY, handoff_id TEXT NOT NULL, status TEXT NOT NULL, provider TEXT NOT NULL, request_digest TEXT NOT NULL, package_digest TEXT NOT NULL, manifest_digest TEXT NOT NULL, changed_file_count INTEGER NOT NULL, event_count INTEGER NOT NULL, validation_checks_json TEXT NOT NULL, preview_json TEXT NOT NULL, quarantine_code TEXT, idempotency_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    database.execute(
        "INSERT INTO returns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("return-existing", "handoff-existing", "contract_validated", "local-contract-self-test", "a" * 64, "b" * 64, "c" * 64, 0, 3, "[]", "{}", None, "idempotency-existing", "2026-08-05T22:00:00+00:00", "2026-08-05T22:00:00+00:00"),
    )
    database.apply_migrations()
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 4") == 1
    assert database.scalar("SELECT COUNT(*) FROM returns") == 1
    database.close()
