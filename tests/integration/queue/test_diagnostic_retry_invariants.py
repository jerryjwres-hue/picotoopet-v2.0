"""诊断重试不得继承历史异常任务的任意执行参数。"""

from __future__ import annotations

from pathlib import Path

import pytest

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import CloudPolicy, TaskStatus
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.queue.state_machine import InvalidTransitionError


def make_repository(tmp_path: Path) -> tuple[Database, DiagnosticQueueRepository]:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database, DiagnosticQueueRepository(database)


def test_retry_refreezes_all_diagnostic_execution_parameters(tmp_path: Path) -> None:
    database, repository = make_repository(tmp_path)
    original = repository.create(
        TaskCreate(
            task_type="system.diagnostic_snapshot",
            payload={
                "schema_version": "1.0",
                "sections": ["queue", "core"],
            },
            priority=1,
            resource_tag="legacy-diagnostic",
            dedupe_key=None,
            max_attempts=9,
            timeout_seconds=3600,
            cloud_policy=CloudPolicy.LOCAL_ONLY,
        )
    )
    repository.transition(original.task_id, TaskStatus.CANCELLED, reason="fixture")

    retried = repository.retry(original.task_id)
    row = database.fetchone(
        "SELECT priority, resource_tag, dedupe_key, max_attempts, "
        "timeout_seconds, cloud_policy, payload_json "
        "FROM tasks WHERE task_id = ?",
        (retried.task_id,),
    )

    assert row is not None
    assert row["priority"] == 50
    assert row["resource_tag"] == "system-diagnostic"
    assert row["dedupe_key"] == "system-diagnostic:active"
    assert row["max_attempts"] == 2
    assert row["timeout_seconds"] == 30
    assert row["cloud_policy"] == CloudPolicy.LOCAL_ONLY.value
    assert retried.payload == {
        "schema_version": "1.0",
        "sections": ["core", "queue"],
    }
    database.close()


def test_retry_rejects_invalid_legacy_diagnostic_payload(tmp_path: Path) -> None:
    database, repository = make_repository(tmp_path)
    original = repository.create(
        TaskCreate(
            task_type="system.diagnostic_snapshot",
            payload={"schema_version": "1.0", "sections": ["logs"]},
            timeout_seconds=3600,
        )
    )
    repository.transition(original.task_id, TaskStatus.CANCELLED, reason="fixture")

    with pytest.raises(InvalidTransitionError, match="请求无效"):
        repository.retry(original.task_id)

    assert database.scalar("SELECT COUNT(*) FROM tasks") == 1
    database.close()
