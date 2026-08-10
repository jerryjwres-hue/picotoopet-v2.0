from datetime import UTC, datetime
from pathlib import Path

from picotoopet_core.db.database import Database
from picotoopet_core.db.schema import (
    MIGRATION_001,
    MIGRATION_002,
    MIGRATION_003,
    MIGRATION_004,
    MIGRATION_005,
)


REQUIRED_CONFIRMATION_COLUMNS = {
    "confirmation_id",
    "handoff_id",
    "provider",
    "status",
    "request_digest",
    "package_digest",
    "budget_json",
    "idempotency_key",
    "confirmed_at",
    "expires_at",
    "preview_json",
}
REQUIRED_PROVIDER_SESSION_COLUMNS = {
    "session_id",
    "handoff_id",
    "provider",
    "status",
    "request_digest",
    "package_digest",
    "budget_json",
    "turns_used",
    "elapsed_seconds",
    "changed_file_count",
    "return_id",
    "failure_code",
    "provider_usage_unknown",
    "idempotency_key",
    "created_at",
    "updated_at",
    "finished_at",
    "preview_json",
}


def _install_first_five(database: Database) -> None:
    now = datetime(2026, 8, 7, 3, 0, tzinfo=UTC).isoformat()
    connection = database.connection
    connection.executescript(MIGRATION_001)
    connection.executescript(MIGRATION_002)
    connection.executescript(MIGRATION_003)
    connection.executescript(MIGRATION_004)
    connection.executescript(MIGRATION_005)
    for version in range(1, 6):
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, now),
        )


def test_migration_six_creates_provider_fact_tables_idempotently(tmp_path: Path) -> None:
    database = Database(tmp_path / "provider.db")
    database.open()
    database.apply_migrations()
    database.apply_migrations()

    confirmation_columns = {
        row["name"]
        for row in database.fetchall("PRAGMA table_info(provider_usage_confirmations)")
    }
    session_columns = {
        row["name"]
        for row in database.fetchall("PRAGMA table_info(provider_sessions)")
    }

    assert REQUIRED_CONFIRMATION_COLUMNS <= confirmation_columns
    assert REQUIRED_PROVIDER_SESSION_COLUMNS <= session_columns
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 11
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 6") == 1
    database.close()


def test_migration_six_preserves_existing_handoff_return_and_broker_rows(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "upgrade.db")
    database.open()
    _install_first_five(database)
    now = "2026-08-07T03:00:00+00:00"
    expires = "2026-08-07T04:00:00+00:00"
    database.execute(
        "INSERT INTO handoffs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?)",
        (
            "handoff-existing",
            "picotoopet-repo-maintenance-v1",
            "existing",
            "existing objective",
            "approved",
            "a" * 64,
            "b" * 64,
            "{}",
            "{}",
            "prepare-existing",
            now,
            now,
            expires,
        ),
    )
    database.execute(
        "INSERT INTO returns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)",
        (
            "return-existing",
            "handoff-existing",
            "contract_validated",
            "local-contract-self-test",
            "a" * 64,
            "b" * 64,
            "c" * 64,
            0,
            3,
            "[]",
            "{}",
            "return-key-existing",
            now,
            now,
        ),
    )
    database.execute(
        "INSERT INTO broker_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)",
        (
            "broker-existing",
            "handoff-existing",
            "completed",
            "local-mock-dev-broker",
            30,
            "a" * 64,
            "b" * 64,
            "return-existing",
            4,
            "d" * 64,
            "broker-key-existing",
            now,
            now,
            now,
            "{}",
        ),
    )

    database.apply_migrations()

    assert database.scalar("SELECT COUNT(*) FROM handoffs") == 1
    assert database.scalar("SELECT COUNT(*) FROM returns") == 1
    assert database.scalar("SELECT COUNT(*) FROM broker_sessions") == 1
    assert database.scalar("SELECT COUNT(*) FROM provider_sessions") == 0
    assert database.scalar("SELECT COUNT(*) FROM schema_migrations") == 11
    database.close()
