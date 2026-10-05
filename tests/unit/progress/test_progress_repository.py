from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from picotoopet_core.db.database import Database
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.progress.models import ProgressUpdate
from picotoopet_core.progress.repository import ProgressRepository
from picotoopet_core.queue.repository import QueueRepository


def _repository(tmp_path: Path) -> tuple[Database, ProgressRepository, str]:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    queue = QueueRepository(database)
    task = queue.create(TaskCreate(task_type="system.noop"))
    return database, ProgressRepository(database), task.task_id


def test_progress_sequence_is_monotonic_per_task(tmp_path: Path) -> None:
    """同一任务的进度序号必须由 Core 原子递增，不能由调用方伪造。"""

    database, repository, task_id = _repository(tmp_path)

    first = repository.append(
        ProgressUpdate(
            task_id=task_id,
            stage="research-search",
            completed=0,
            total=2,
            message="准备搜索 2 个查询",
            component="research",
        )
    )
    second = repository.append(
        ProgressUpdate(
            task_id=task_id,
            stage="research-search",
            completed=1,
            total=2,
            message="搜索 1/2 完成",
            component="research",
            details={"query_index": 1},
        )
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert second.created_at >= first.created_at
    database.close()


def test_progress_snapshot_is_truthful_and_bounded(tmp_path: Path) -> None:
    """快照只基于持久事件计算真实百分比，并限制最近活动数量。"""

    database, repository, task_id = _repository(tmp_path)
    for index in range(60):
        repository.append(
            ProgressUpdate(
                task_id=task_id,
                stage="research-search",
                completed=index + 1,
                total=60,
                message=f"搜索 {index + 1}/60 完成",
                component="research",
            )
        )

    snapshot = repository.snapshot(task_id, recent_limit=50)

    assert snapshot.stage == "research-search"
    assert snapshot.completed == 60
    assert snapshot.total == 60
    assert snapshot.percent == 100.0
    assert snapshot.latest_message == "搜索 60/60 完成"
    assert snapshot.last_activity_at is not None
    assert len(snapshot.recent_events) == 50
    assert snapshot.recent_events[0].sequence == 11
    assert snapshot.recent_events[-1].sequence == 60
    database.close()


def test_progress_without_total_never_invents_percent(tmp_path: Path) -> None:
    """没有可验证总量时 percent 必须为空，禁止按时间伪造进度。"""

    database, repository, task_id = _repository(tmp_path)
    repository.append(
        ProgressUpdate(
            task_id=task_id,
            stage="local-analysis",
            message="本地模型正在分析",
            component="ollama",
        )
    )

    snapshot = repository.snapshot(task_id)

    assert snapshot.completed is None
    assert snapshot.total is None
    assert snapshot.percent is None
    database.close()


def test_progress_rejects_invalid_counts_and_oversized_details() -> None:
    """进度 payload 必须保持有界且 completed 不得超过 total。"""

    with pytest.raises(ValidationError):
        ProgressUpdate(
            task_id="task-a",
            stage="research-search",
            completed=3,
            total=2,
            message="invalid",
            component="research",
        )

    with pytest.raises(ValidationError):
        ProgressUpdate(
            task_id="task-a",
            stage="research-search",
            completed=1,
            total=2,
            message="oversized",
            component="research",
            details={"payload": "x" * 5000},
        )
