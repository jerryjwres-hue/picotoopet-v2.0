"""诊断结果元数据与任务终态原子提交回归。"""

from __future__ import annotations

from pathlib import Path

import pytest

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.events.outbox import EventOutbox
from picotoopet_core.queue.repository import QueueRepository
from picotoopet_core.results.store import ResultStore


def make_repository(
    tmp_path: Path,
) -> tuple[Database, QueueRepository, ResultStore, EventOutbox]:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    outbox = EventOutbox(database)
    store = ResultStore(tmp_path / "results")
    return database, QueueRepository(database, outbox=outbox), store, outbox


def test_complete_with_result_is_one_database_transaction(tmp_path: Path) -> None:
    database, repository, store, _ = make_repository(tmp_path)
    task = repository.create(
        TaskCreate(task_type="system.diagnostic_snapshot", timeout_seconds=30)
    )
    leased = repository.lease_next(
        "worker-m4",
        lease_seconds=60,
        supported_task_types=("system.diagnostic_snapshot",),
    )
    assert leased is not None
    stored = store.put_json(
        {"schema_version": "1.0", "checks": []},
        result_type="system.diagnostic_snapshot",
        max_bytes=64 * 1024,
    )

    completed = repository.complete_leased_with_result(
        task.task_id,
        worker_id="worker-m4",
        stored_result=stored,
        schema_version="1.0",
    )

    assert completed.status is TaskStatus.COMPLETED
    assert completed.result_id is not None
    result = database.fetchone(
        "SELECT * FROM results WHERE result_id = ?",
        (completed.result_id,),
    )
    assert result is not None
    assert result["task_id"] == task.task_id
    assert result["object_hash"] == stored.object_hash
    attempt = database.fetchone(
        "SELECT * FROM task_attempts WHERE task_id = ?",
        (task.task_id,),
    )
    assert attempt is not None
    assert attempt["status"] == TaskStatus.COMPLETED.value
    topics = {
        row["topic"]
        for row in database.fetchall(
            "SELECT topic FROM event_outbox ORDER BY rowid",
        )
    }
    assert "task.updated" in topics
    assert "result.created" in topics
    database.close()


def test_complete_with_result_rolls_back_metadata_and_task_on_outbox_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, repository, store, outbox = make_repository(tmp_path)
    task = repository.create(TaskCreate(task_type="system.diagnostic_snapshot"))
    repository.lease_next(
        "worker-m4",
        lease_seconds=60,
        supported_task_types=("system.diagnostic_snapshot",),
    )
    stored = store.put_json(
        {"schema_version": "1.0"},
        result_type="system.diagnostic_snapshot",
        max_bytes=64 * 1024,
    )
    original_append = outbox.append_in_transaction

    def fail_result_created(*args, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("topic") == "result.created":
            raise RuntimeError("injected outbox failure")
        return original_append(*args, **kwargs)

    monkeypatch.setattr(outbox, "append_in_transaction", fail_result_created)

    with pytest.raises(RuntimeError, match="injected outbox failure"):
        repository.complete_leased_with_result(
            task.task_id,
            worker_id="worker-m4",
            stored_result=stored,
            schema_version="1.0",
        )

    current = repository.get(task.task_id)
    assert current.status is TaskStatus.RUNNING
    assert current.result_id is None
    assert database.fetchone(
        "SELECT result_id FROM results WHERE task_id = ?",
        (task.task_id,),
    ) is None
    database.close()
