from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from time import sleep

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskCreate, TaskRecord
from picotoopet_core.queue.repository import QueueRepository
from picotoopet_core.worker.handlers import HandlerResult
from picotoopet_core.worker.runtime import WorkerRuntime
from picotoopet_core.worker.state import WorkerStateStore


def make_runtime(
    tmp_path: Path,
) -> tuple[Database, QueueRepository, WorkerRuntime, WorkerStateStore]:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    queue = QueueRepository(database)
    store = WorkerStateStore(tmp_path / "state" / "worker-status.json", stale_after_seconds=30)
    runtime = WorkerRuntime(
        queue=queue,
        state_store=store,
        worker_id="worker-m4",
        lease_seconds=60,
        heartbeat_seconds=5,
    )
    return database, queue, runtime, store


def test_worker_runtime_processes_noop_without_touching_unknown_tasks(tmp_path: Path) -> None:
    """基础 Worker 只执行 system.noop，旧 analysis 必须保持排队。"""

    database, queue, runtime, store = make_runtime(tmp_path)
    historical = queue.create(TaskCreate(task_type="analysis", priority=1))
    noop = queue.create(TaskCreate(task_type="system.noop", payload={"message": "ok"}))

    result = runtime.run_once()

    assert result.processed is True
    assert result.succeeded is True
    assert result.task_id == noop.task_id
    assert queue.get(noop.task_id).status is TaskStatus.COMPLETED
    assert queue.get(historical.task_id).status is TaskStatus.QUEUED
    status = store.read_status()
    assert status.available is True
    assert status.state == "online"
    assert status.active_task_id is None
    assert status.supported_task_types == ["system.noop"]
    database.close()


def test_worker_runtime_records_handler_failure_without_crashing_loop(tmp_path: Path) -> None:
    """处理器异常必须形成受控 Failed 终态和脱敏错误。"""

    database, queue, runtime, store = make_runtime(tmp_path)
    task = queue.create(TaskCreate(task_type="system.noop", payload={"raise_error": True}))

    result = runtime.run_once()

    assert result.processed is True
    assert result.succeeded is False
    failed = queue.get(task.task_id)
    assert failed.status is TaskStatus.FAILED
    assert failed.error_code == "WORKER_HANDLER_ERROR"
    assert failed.error_message == "system.noop handler failed"
    assert store.read_status().state == "degraded"
    database.close()


def test_worker_runtime_keeps_liveness_fresh_while_handler_runs(tmp_path: Path) -> None:
    """长任务执行期间 Worker 状态心跳必须独立刷新，不能被误判离线。"""

    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    queue = QueueRepository(database)
    store = WorkerStateStore(
        tmp_path / "state" / "worker-status.json",
        stale_after_seconds=1,
    )
    started = Event()
    release = Event()

    def blocking_handler(task: TaskRecord) -> HandlerResult:
        started.set()
        if not release.wait(timeout=5):
            raise RuntimeError("test handler release timed out")
        return HandlerResult(summary={"task_type": task.task_type})

    runtime = WorkerRuntime(
        queue=queue,
        state_store=store,
        worker_id="worker-m4",
        handlers={"test.blocking": blocking_handler},
        lease_seconds=6,
        heartbeat_seconds=1,
    )
    queue.create(TaskCreate(task_type="test.blocking"))
    runner = Thread(target=runtime.run_once, daemon=True)
    runner.start()

    assert started.wait(timeout=2)
    sleep(1.25)
    during = store.read_status()

    release.set()
    runner.join(timeout=5)
    assert runner.is_alive() is False
    assert during.state == "online"
    assert during.reason == "executing"
    assert during.available is True
    database.close()


def test_worker_state_store_reports_missing_stale_and_corrupt_states(tmp_path: Path) -> None:
    """API 状态读取必须保守区分未部署、离线和损坏。"""

    path = tmp_path / "Application Support" / "PicotooPetV2" / "state" / "worker-status.json"
    store = WorkerStateStore(path, stale_after_seconds=30)

    missing = store.read_status(now=datetime(2026, 8, 2, tzinfo=UTC))
    assert missing.state == "not_deployed"
    assert missing.available is False

    store.publish(
        state="online",
        reason="idle",
        worker_id="worker-m4",
        supported_task_types=("system.noop",),
        active_task_id=None,
        observed_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    fresh = store.read_status(now=datetime(2026, 8, 2, tzinfo=UTC))
    assert fresh.state == "online"
    assert fresh.available is True

    stale = store.read_status(
        now=datetime(2026, 8, 2, tzinfo=UTC) + timedelta(seconds=31)
    )
    assert stale.state == "offline"
    assert stale.available is False
    assert stale.reason == "worker_heartbeat_stale"

    path.write_text("{not-json", encoding="utf-8")
    corrupt = store.read_status(now=datetime(2026, 8, 2, tzinfo=UTC))
    assert corrupt.state == "degraded"
    assert corrupt.available is False
    assert corrupt.reason == "worker_status_corrupt"
