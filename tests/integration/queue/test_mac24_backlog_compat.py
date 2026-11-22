"""Synthetic regression based on the Mac read-only acceptance inventory (2026-11-22).

No user database is read, copied, mutated, repaired, or upgraded.
The synthetic backlog reproduces 1,502 unsupported Queued records and 1,076
historical Failed records at Schema 24. No production Worker or model runs.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from picotoopet_core.config import AppSettings, RuntimePaths
from picotoopet_core.db.database import CURRENT_SCHEMA_VERSION, Database
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.services import build_services
from picotoopet_core.worker.handlers import default_handlers

UNSUPPORTED = "phase2.link.acceptance"
QUEUED_COUNT = 1502
FAILED_COUNT = 1076
TABLES = (
    "tasks", "task_attempts", "task_events", "approvals",
    "artifacts", "production_jobs",
)


def _snapshot_state(database: Database) -> dict:
    # 01. Preserve original task identity and status; no retry or cleanup.
    rows = database.fetchall(
        "SELECT task_id, task_type, status, attempt_count, lease_owner, "
        "lease_expires_at FROM tasks ORDER BY task_id"
    )
    return {
        "tasks": [tuple(row) for row in rows],
        "counts": {
            name: int(database.scalar(f"SELECT COUNT(*) FROM {name}") or 0)
            for name in TABLES
        },
    }


def _build_synthetic_baseline(path: Path) -> None:
    database = Database(path)
    database.open()
    database.apply_migrations()
    now = datetime.now(UTC).isoformat()
    # 02. Only fixtures, not copied customer records; a single transaction.
    with database.transaction() as connection:
        connection.executemany(
            "INSERT INTO tasks (task_id,task_type,status,priority,payload_json,"
            "attempt_count,max_attempts,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                (
                    f"old-queued-{index:04d}", UNSUPPORTED,
                    TaskStatus.QUEUED.value, 1, "{}", 0, 3, now, now,
                )
                for index in range(QUEUED_COUNT)
            ),
        )
        connection.executemany(
            "INSERT INTO tasks (task_id,task_type,status,priority,payload_json,"
            "attempt_count,max_attempts,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                (
                    f"old-failed-{index:04d}", UNSUPPORTED,
                    TaskStatus.FAILED.value, 1, "{}", 3, 3, now, now,
                )
                for index in range(FAILED_COUNT)
            ),
        )
    assert int(database.scalar("SELECT MAX(version) FROM schema_migrations")) == 24
    database.close()


def test_existing_mac_24_backlog_reopens_without_replaying_old_tasks(tmp_path: Path) -> None:
    # 03. Simulate the earlier Mac installation, then make a consistent offline
    #     SQLite backup before exercising candidate code on that backup only.
    baseline = tmp_path / "synthetic-mac-baseline.db"
    candidate_root = tmp_path / "isolated-candidate-runtime"
    snapshot = candidate_root / "database" / "core.db"
    snapshot.parent.mkdir(parents=True)
    _build_synthetic_baseline(baseline)
    with sqlite3.connect(baseline) as source, sqlite3.connect(snapshot) as destination:
        source.backup(destination)

    # 04. Build the actual candidate Core service graph against only the
    #     isolated backup copy; this exercises startup schema/ledger behavior.
    settings = AppSettings(
        paths=RuntimePaths.from_root(candidate_root),
        api_token="synthetic-token-never-installed-0001",
        api_host="127.0.0.1",
    )
    services = build_services(settings)
    database = services.database
    before = _snapshot_state(database)
    assert before["counts"]["tasks"] == QUEUED_COUNT + FAILED_COUNT
    assert before["counts"]["task_attempts"] == 0
    assert before["counts"]["artifacts"] == 0
    assert before["counts"]["approvals"] == 0
    assert before["counts"]["production_jobs"] == 0

    # 05. Reapplying Schema 24 and querying Worker capabilities must not
    #     silently turn the legacy link acceptance backlog into runnable jobs.
    assert CURRENT_SCHEMA_VERSION == 24
    database.apply_migrations()
    assert int(database.scalar("SELECT MAX(version) FROM schema_migrations")) == 24
    assert int(database.scalar("SELECT COUNT(*) FROM canonical_evidence")) == 0
    assert int(database.scalar("PRAGMA user_version")) == 0
    assert database.scalar("PRAGMA quick_check") == "ok"
    handlers = default_handlers()
    assert UNSUPPORTED not in handlers
    supported = tuple(sorted(handlers))
    assert supported

    queue = DiagnosticQueueRepository(database)
    assert queue.recover_expired_supported_leases(
        supported_task_types=supported
    ) == []
    assert queue.promote_retries(supported_task_types=supported) == []
    assert queue.lease_next(
        "synthetic-mac-worker", supported_task_types=supported
    ) is None
    assert queue.lease_next(
        "synthetic-mac-worker", supported_task_types=()
    ) is None

    after = _snapshot_state(database)
    assert after == before
    assert int(database.scalar("SELECT COUNT(*) FROM tasks WHERE lease_owner IS NOT NULL")) == 0
    assert int(database.scalar("SELECT COUNT(*) FROM task_attempts")) == 0
    database.close()

    # 06. The simulated original installed baseline is never altered by the
    #     candidate copy's migration or Worker validation.
    with sqlite3.connect(f"file:{baseline}?mode=ro", uri=True) as source:
        assert source.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == QUEUED_COUNT + FAILED_COUNT
        assert source.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_unsupported_type_is_not_claimed_even_if_supported_work_is_present(
    tmp_path: Path,
) -> None:
    # 07. Higher-priority legacy backlog cannot starve or hijack an explicitly
    #     supported task. All legacy rows stay in their original statuses.
    database = Database(tmp_path / "isolated-supported-fixture.db")
    database.open()
    database.apply_migrations()
    queue = DiagnosticQueueRepository(database)
    from picotoopet_core.domain.models import TaskCreate

    legacy = queue.create(TaskCreate(task_type=UNSUPPORTED, priority=1))
    supported = queue.create(TaskCreate(task_type="system.noop", priority=500))
    claimed = queue.lease_next("synthetic-worker", supported_task_types=("system.noop",))
    assert claimed is not None and claimed.task_id == supported.task_id
    assert queue.get(legacy.task_id).status == TaskStatus.QUEUED
    assert int(database.scalar(
        "SELECT COUNT(*) FROM task_attempts WHERE task_id = ?", (legacy.task_id,)
    )) == 0
    database.close()
