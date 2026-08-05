"""诊断任务取消意图、竞态和重试恢复回归。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.queue.repository import LeaseOwnershipError
from picotoopet_core.results.store import ResultStore


def make_repository(
    tmp_path: Path,
) -> tuple[Database, DiagnosticQueueRepository, ResultStore]:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return (
        database,
        DiagnosticQueueRepository(database),
        ResultStore(tmp_path / "results"),
    )


def test_queued_cancel_is_immediate_and_running_cancel_is_owner_completed(
    tmp_path: Path,
) -> None:
    database, repository, _ = make_repository(tmp_path)
    queued = repository.create(TaskCreate(task_type="system.diagnostic_snapshot"))

    cancelled = repository.request_cancel(queued.task_id)

    assert cancelled.status is TaskStatus.CANCELLED

    running = repository.create(TaskCreate(task_type="system.diagnostic_snapshot"))
    repository.lease_next(
        "worker-m4",
        supported_task_types=("system.diagnostic_snapshot",),
    )

    pending = repository.request_cancel(running.task_id)

    assert pending.status is TaskStatus.RUNNING
    assert repository.is_cancel_requested(running.task_id, worker_id="worker-m4") is True

    terminal = repository.cancel_leased(running.task_id, worker_id="worker-m4")
    assert terminal.status is TaskStatus.CANCELLED
    assert terminal.result_id is None
    database.close()


def test_cancel_intent_blocks_result_commit_and_preserves_one_terminal_state(
    tmp_path: Path,
) -> None:
    database, repository, store = make_repository(tmp_path)
    task = repository.create(TaskCreate(task_type="system.diagnostic_snapshot"))
    repository.lease_next(
        "worker-m4",
        supported_task_types=("system.diagnostic_snapshot",),
    )
    repository.request_cancel(task.task_id)
    stored = store.put_json(
        {"schema_version": "1.0"},
        result_type="system.diagnostic_snapshot",
        max_bytes=64 * 1024,
    )

    with pytest.raises(LeaseOwnershipError, match="取消"):
        repository.complete_leased_with_result(
            task.task_id,
            worker_id="worker-m4",
            stored_result=stored,
            schema_version="1.0",
        )

    cancelled = repository.cancel_leased(task.task_id, worker_id="worker-m4")
    assert cancelled.status is TaskStatus.CANCELLED
    assert database.fetchone(
        "SELECT result_id FROM results WHERE task_id = ?",
        (task.task_id,),
    ) is None
    database.close()


def test_expired_lease_with_cancel_intent_recovers_to_cancelled(tmp_path: Path) -> None:
    """Worker 崩溃不能把已请求取消的任务恢复成 Retrying。"""

    database, repository, _ = make_repository(tmp_path)
    task = repository.create(TaskCreate(task_type="system.diagnostic_snapshot"))
    leased = repository.lease_next(
        "dead-worker",
        lease_seconds=60,
        supported_task_types=("system.diagnostic_snapshot",),
    )
    assert leased is not None
    repository.request_cancel(task.task_id)
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    database.execute(
        "UPDATE tasks SET lease_expires_at = ? WHERE task_id = ?",
        (expired_at.isoformat(), task.task_id),
    )

    recovered = repository.recover_expired_supported_leases(
        supported_task_types=("system.diagnostic_snapshot", "system.noop"),
    )

    assert recovered == [task.task_id]
    current = repository.get(task.task_id)
    assert current.status is TaskStatus.CANCELLED
    assert current.result_id is None
    assert current.error_code == "WORKER_TASK_CANCELLED"
    attempt = database.fetchone(
        "SELECT status, error_code, finished_at FROM task_attempts WHERE task_id = ?",
        (task.task_id,),
    )
    assert attempt is not None
    assert attempt["status"] == TaskStatus.CANCELLED.value
    assert attempt["error_code"] == "WORKER_TASK_CANCELLED"
    assert attempt["finished_at"] is not None
    assert database.fetchone(
        "SELECT result_id FROM results WHERE task_id = ?",
        (task.task_id,),
    ) is None
    database.close()


def test_retry_promotion_only_touches_explicit_supported_task_types(tmp_path: Path) -> None:
    database, repository, _ = make_repository(tmp_path)
    diagnostic = repository.create(TaskCreate(task_type="system.diagnostic_snapshot"))
    analysis = repository.create(TaskCreate(task_type="analysis"))
    repository.lease_next(
        "worker-diagnostic",
        supported_task_types=("system.diagnostic_snapshot",),
    )
    repository.transition(
        diagnostic.task_id,
        TaskStatus.RETRYING,
        reason="test_retry",
    )
    repository.lease_next(
        "worker-analysis",
        supported_task_types=("analysis",),
    )
    repository.transition(
        analysis.task_id,
        TaskStatus.RETRYING,
        reason="test_retry",
    )

    promoted = repository.promote_retries(
        supported_task_types=("system.diagnostic_snapshot",),
        limit=100,
    )

    assert promoted == [diagnostic.task_id]
    assert repository.get(diagnostic.task_id).status is TaskStatus.QUEUED
    assert repository.get(analysis.task_id).status is TaskStatus.RETRYING
    database.close()
