from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import CloudPolicy, TaskStatus
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.queue.repository import QueueRepository
from picotoopet_core.queue.state_machine import InvalidTransitionError


def make_repository(tmp_path: Path) -> tuple[Database, QueueRepository]:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database, QueueRepository(database)


def make_diagnostic_repository(
    tmp_path: Path,
) -> tuple[Database, DiagnosticQueueRepository]:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database, DiagnosticQueueRepository(database)


def test_queue_is_idempotent_deduplicated_and_priority_ordered(tmp_path: Path) -> None:
    """相同请求不得重复创建，租约必须按优先级领取。"""

    database, repository = make_repository(tmp_path)
    first = repository.create(
        TaskCreate(task_type="report", priority=200, idempotency_key="idem-1", dedupe_key="same")
    )
    same_idempotent = repository.create(
        TaskCreate(task_type="report", priority=1, idempotency_key="idem-1")
    )
    same_dedupe = repository.create(
        TaskCreate(task_type="report", priority=1, dedupe_key="same")
    )
    urgent = repository.create(TaskCreate(task_type="urgent", priority=10))

    assert same_idempotent.task_id == first.task_id
    assert same_dedupe.task_id == first.task_id
    leased = repository.lease_next("worker-1", lease_seconds=30)
    assert leased is not None
    assert leased.task_id == urgent.task_id
    assert leased.status is TaskStatus.RUNNING
    assert leased.attempt_count == 1
    database.close()


def test_queue_recovers_expired_lease_and_protects_terminal_state(tmp_path: Path) -> None:
    """崩溃租约应进入重试，完成任务不能回到运行态。"""

    database, repository = make_repository(tmp_path)
    task = repository.create(TaskCreate(task_type="analysis"))
    leased = repository.lease_next("worker-1", lease_seconds=30)
    assert leased is not None

    past = datetime.now(UTC) - timedelta(minutes=5)
    database.execute(
        "UPDATE tasks SET lease_expires_at = ? WHERE task_id = ?",
        (past.isoformat(), task.task_id),
    )
    recovered = repository.recover_expired_leases(datetime.now(UTC))
    assert recovered == [task.task_id]
    assert repository.get(task.task_id).status is TaskStatus.RETRYING

    repository.transition(task.task_id, TaskStatus.QUEUED, reason="retry")
    repository.lease_next("worker-2", lease_seconds=30)
    repository.transition(task.task_id, TaskStatus.COMPLETED, reason="done")
    with pytest.raises(InvalidTransitionError):
        repository.transition(task.task_id, TaskStatus.RUNNING, reason="illegal")
    database.close()


def test_cloud_manual_task_waits_for_approval(tmp_path: Path) -> None:
    """云端任务创建后必须停在人工审批状态。"""

    database, repository = make_repository(tmp_path)
    task = repository.create(
        TaskCreate(task_type="cloud_render", cloud_policy=CloudPolicy.CLOUD_MANUAL)
    )
    assert task.status is TaskStatus.WAITING_FOR_APPROVAL
    database.close()


def test_retry_creates_new_child_task_instead_of_reopening_terminal_task(tmp_path: Path) -> None:
    """重试必须创建新任务，原终态任务保持不可变。"""

    database, repository = make_repository(tmp_path)
    original = repository.create(TaskCreate(task_type="analysis", payload={"a": 1}))
    repository.transition(original.task_id, TaskStatus.CANCELLED, reason="cancel")

    retried = repository.retry(original.task_id)

    assert retried.task_id != original.task_id
    assert retried.parent_task_id == original.task_id
    assert retried.status is TaskStatus.QUEUED
    assert repository.get(original.task_id).status is TaskStatus.CANCELLED
    assert [item.task_id for item in repository.list()] == [retried.task_id, original.task_id]
    database.close()


def test_diagnostic_repository_keeps_non_diagnostic_retry_semantics(
    tmp_path: Path,
) -> None:
    """Core 的增强仓储不得为普通任务制造嵌套事务或改变重试语义。"""

    database, repository = make_diagnostic_repository(tmp_path)
    original = repository.create(TaskCreate(task_type="analysis", payload={"a": 1}))
    repository.transition(original.task_id, TaskStatus.CANCELLED, reason="cancel")

    retried = repository.retry(original.task_id)

    assert retried.task_id != original.task_id
    assert retried.parent_task_id == original.task_id
    assert retried.status is TaskStatus.QUEUED
    row = database.fetchone(
        "SELECT idempotency_key, dedupe_key FROM tasks WHERE task_id = ?",
        (retried.task_id,),
    )
    assert row is not None
    assert row["idempotency_key"] is None
    assert row["dedupe_key"] is None
    database.close()


def test_diagnostic_retry_replay_returns_same_child_and_preserves_dedupe_key(
    tmp_path: Path,
) -> None:
    """双击或网络重放同一次诊断重试不得生成多个活动子任务。"""

    database, repository = make_diagnostic_repository(tmp_path)
    original = repository.create(
        TaskCreate(
            task_type="system.diagnostic_snapshot",
            payload={"schema_version": "1.0", "sections": ["core"]},
            dedupe_key="system-diagnostic:active",
        )
    )
    repository.transition(original.task_id, TaskStatus.CANCELLED, reason="cancel")

    first = repository.retry(original.task_id)
    replay = repository.retry(original.task_id)

    assert replay.task_id == first.task_id
    assert replay.parent_task_id == original.task_id
    rows = database.fetchall(
        "SELECT task_id, idempotency_key, dedupe_key FROM tasks ORDER BY rowid"
    )
    assert len(rows) == 2
    assert rows[1]["idempotency_key"] == f"retry:{original.task_id}"
    assert rows[1]["dedupe_key"] == "system-diagnostic:active"
    database.close()


def test_diagnostic_retry_returns_existing_active_task_with_same_dedupe_key(
    tmp_path: Path,
) -> None:
    """已有活动诊断时，重试不得绕过全局活动去重。"""

    database, repository = make_diagnostic_repository(tmp_path)
    original = repository.create(
        TaskCreate(
            task_type="system.diagnostic_snapshot",
            dedupe_key="system-diagnostic:active",
        )
    )
    repository.transition(original.task_id, TaskStatus.CANCELLED, reason="cancel")
    active = repository.create(
        TaskCreate(
            task_type="system.diagnostic_snapshot",
            dedupe_key="system-diagnostic:active",
        )
    )

    retried = repository.retry(original.task_id)

    assert retried.task_id == active.task_id
    assert len(repository.list()) == 2
    database.close()


def test_retry_writes_parent_link_inside_creation_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """重试必须在创建 INSERT 中写入 parent_task_id，不做事务外补写。"""

    database, repository = make_repository(tmp_path)
    original = repository.create(TaskCreate(task_type="analysis", payload={"a": 1}))
    repository.transition(original.task_id, TaskStatus.CANCELLED, reason="cancel")
    original_execute = database.execute

    def fail_parent_link(sql: str, parameters=()):
        """任何事务外 parent_task_id 补写都会让测试失败。"""

        if "parent_task_id" in sql:
            raise RuntimeError("simulated parent link failure")
        return original_execute(sql, parameters)

    monkeypatch.setattr(database, "execute", fail_parent_link)

    try:
        retried = repository.retry(original.task_id)
    except RuntimeError:
        retried = None

    task_count = database.connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    assert retried is not None
    assert retried.parent_task_id == original.task_id
    assert task_count == 2
    database.close()


def test_list_can_exclude_diagnostic_tasks_and_apply_limit(tmp_path: Path) -> None:
    """桌面初始同步不得把高样本诊断任务全部载入内存。"""

    database, repository = make_repository(tmp_path)
    repository.create(TaskCreate(task_type="visible-1", resource_tag="desktop"))
    repository.create(TaskCreate(task_type="diagnostic", resource_tag="phase2-diagnostic"))
    newest = repository.create(TaskCreate(task_type="visible-2", resource_tag="desktop"))

    records = repository.list(exclude_resource_tag="phase2-diagnostic", limit=1)

    assert [record.task_id for record in records] == [newest.task_id]
    database.close()
