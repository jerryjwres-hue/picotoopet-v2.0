from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.queue.repository import LeaseOwnershipError, QueueRepository


def make_repository(tmp_path: Path) -> tuple[Database, QueueRepository]:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database, QueueRepository(database)


def test_worker_only_leases_explicitly_supported_task_types(tmp_path: Path) -> None:
    """基础 Worker 不得误领取已有 analysis 等未知任务。"""

    database, repository = make_repository(tmp_path)
    historical = repository.create(TaskCreate(task_type="analysis", priority=1))
    supported = repository.create(TaskCreate(task_type="system.noop", priority=100))

    leased = repository.lease_next(
        "worker-m4",
        lease_seconds=30,
        supported_task_types=("system.noop",),
    )

    assert leased is not None
    assert leased.task_id == supported.task_id
    assert repository.get(historical.task_id).status is TaskStatus.QUEUED
    assert repository.lease_next(
        "worker-m4",
        supported_task_types=(),
    ) is None
    database.close()


def test_worker_lease_creates_attempt_and_owner_guarded_heartbeat(tmp_path: Path) -> None:
    """领取必须创建 attempt，续租必须验证所有权。"""

    database, repository = make_repository(tmp_path)
    task = repository.create(TaskCreate(task_type="system.noop"))
    leased = repository.lease_next(
        "worker-m4",
        lease_seconds=30,
        supported_task_types=("system.noop",),
    )
    assert leased is not None

    attempt = database.fetchone(
        "SELECT * FROM task_attempts WHERE task_id = ?",
        (task.task_id,),
    )
    assert attempt is not None
    assert attempt["worker_id"] == "worker-m4"
    assert attempt["status"] == TaskStatus.RUNNING.value

    before = database.fetchone(
        "SELECT lease_expires_at FROM tasks WHERE task_id = ?",
        (task.task_id,),
    )
    assert before is not None
    renewed = repository.renew_lease(
        task.task_id,
        worker_id="worker-m4",
        lease_seconds=120,
    )
    assert renewed.status is TaskStatus.RUNNING
    after = database.fetchone(
        "SELECT lease_expires_at FROM tasks WHERE task_id = ?",
        (task.task_id,),
    )
    assert after is not None
    assert datetime.fromisoformat(after["lease_expires_at"]) > datetime.fromisoformat(
        before["lease_expires_at"]
    )

    with pytest.raises(LeaseOwnershipError):
        repository.renew_lease(task.task_id, worker_id="worker-other")
    database.close()


def test_only_lease_owner_can_complete_or_fail_running_task(tmp_path: Path) -> None:
    """错误 Worker、过期租约和取消任务不得被终态覆盖。"""

    database, repository = make_repository(tmp_path)
    task = repository.create(TaskCreate(task_type="system.noop"))
    leased = repository.lease_next(
        "worker-m4",
        supported_task_types=("system.noop",),
    )
    assert leased is not None

    with pytest.raises(LeaseOwnershipError):
        repository.complete_leased(task.task_id, worker_id="worker-other")

    completed = repository.complete_leased(task.task_id, worker_id="worker-m4")
    assert completed.status is TaskStatus.COMPLETED
    attempt = database.fetchone(
        "SELECT * FROM task_attempts WHERE task_id = ?",
        (task.task_id,),
    )
    assert attempt is not None
    assert attempt["status"] == TaskStatus.COMPLETED.value
    assert attempt["finished_at"] is not None

    second = repository.create(TaskCreate(task_type="system.noop"))
    repository.lease_next("worker-m4", supported_task_types=("system.noop",))
    failed = repository.fail_leased(
        second.task_id,
        worker_id="worker-m4",
        error_code="HANDLER_ERROR",
        error_message="safe failure",
    )
    assert failed.status is TaskStatus.FAILED
    assert failed.error_code == "HANDLER_ERROR"
    assert failed.error_message == "safe failure"

    third = repository.create(TaskCreate(task_type="system.noop"))
    repository.lease_next("worker-m4", supported_task_types=("system.noop",))
    database.execute(
        "UPDATE tasks SET lease_expires_at = ? WHERE task_id = ?",
        ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), third.task_id),
    )
    with pytest.raises(LeaseOwnershipError):
        repository.complete_leased(third.task_id, worker_id="worker-m4")
    database.close()
