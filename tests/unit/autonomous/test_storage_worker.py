"""P4 storage maintenance acts only on disposable and explicitly completed data."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from picotoopet_core.autonomous.storage_worker import StorageMaintenanceCoordinator
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskRecord


def _task() -> TaskRecord:
    now = datetime.now(UTC)
    return TaskRecord(
        task_id="task-storage-maintenance",
        task_type="autonomous.storage_maintenance.v1",
        status=TaskStatus.RUNNING,
        priority=900,
        resource_tag="workflow:wf-storage",
        payload={"grace_hours": 24, "max_compactions": 20},
        attempt_count=1,
        max_attempts=2,
        timeout_seconds=300,
        created_at=now,
        updated_at=now,
    )


def test_storage_task_compacts_completed_and_deletes_only_expired_disposable(tmp_path: Path) -> None:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    coordinator = StorageMaintenanceCoordinator(paths)

    completed = coordinator.completed_dir / "research.json"
    completed.write_bytes(b"verified useful evidence\n" * 500)
    disposable = paths.autonomous_disposable_dir / "crawl.tmp"
    disposable.write_bytes(b"temporary")
    old = (datetime.now(UTC) - timedelta(hours=48)).timestamp()
    os.utime(disposable, (old, old))
    untouched = paths.autonomous_staging_dir / "not-completed.json"
    untouched.write_text("must stay", encoding="utf-8")

    result = coordinator.handler(_task())

    assert result.result_document is not None
    assert result.result_document["files_compacted"] == 1
    assert result.result_document["disposable_files_deleted"] == 1
    assert not completed.exists()
    assert not disposable.exists()
    assert untouched.exists()
    assert any(paths.autonomous_archive_dir.glob("completed-*.gz"))


def test_storage_task_is_idempotent_after_completed_directory_is_empty(tmp_path: Path) -> None:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    coordinator = StorageMaintenanceCoordinator(paths)
    completed = coordinator.completed_dir / "one.json"
    completed.write_bytes(b"useful" * 1000)

    first = coordinator.handler(_task())
    second = coordinator.handler(_task())

    assert first.result_document is not None
    assert first.result_document["files_compacted"] == 1
    assert second.result_document is not None
    assert second.result_document["files_compacted"] == 0
    assert second.result_document["compaction_failures"] == 0
