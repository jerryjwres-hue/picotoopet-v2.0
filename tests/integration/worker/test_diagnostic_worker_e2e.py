"""Slice D Worker 诊断任务端到端状态和结果回归。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from picotoopet_core.db.database import Database
from picotoopet_core.diagnostics.collector import collect_snapshot
from picotoopet_core.diagnostics.models import (
    DiagnosticFacts,
    DiagnosticSnapshotRequest,
)
from picotoopet_core.diagnostics.subprocess_runner import (
    DiagnosticCancelledError,
    DiagnosticTimeoutError,
)
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.results.store import ResultStore
from picotoopet_core.worker.runtime import WorkerRuntime
from picotoopet_core.worker.state import WorkerStateStore


class SuccessfulRunner:
    def run(
        self,
        request: DiagnosticSnapshotRequest,
        facts: DiagnosticFacts,
        *,
        output_dir: Path | str,
        timeout_seconds: float,
        cancel_requested,
    ) -> Path:  # type: ignore[no-untyped-def]
        assert timeout_seconds == 30
        assert cancel_requested() is False
        result = collect_snapshot(request, facts)
        output = Path(output_dir) / "diagnostic-result.json"
        output.write_text(result.model_dump_json(), encoding="utf-8")
        return output


class CancellingRunner:
    def __init__(self, cancel) -> None:  # type: ignore[no-untyped-def]
        self.cancel = cancel

    def run(self, *args, **kwargs) -> Path:  # type: ignore[no-untyped-def]
        self.cancel()
        assert kwargs["cancel_requested"]() is True
        raise DiagnosticCancelledError("cancelled")


class TimeoutRunner:
    def run(self, *args, **kwargs) -> Path:  # type: ignore[no-untyped-def]
        raise DiagnosticTimeoutError("timeout")


class CancelOnPutResultStore(ResultStore):
    """在对象写入前注入取消，复现最后检查与提交事务之间的竞态。"""

    def __init__(self, root: Path, cancel) -> None:  # type: ignore[no-untyped-def]
        super().__init__(root)
        self.cancel = cancel

    def put_json(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.cancel()
        return super().put_json(*args, **kwargs)


def make_runtime(
    tmp_path: Path,
    *,
    runner,
) -> tuple[Database, DiagnosticQueueRepository, WorkerRuntime, ResultStore]:  # type: ignore[no-untyped-def]
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    queue = DiagnosticQueueRepository(database)
    result_store = ResultStore(tmp_path / "results")
    state_store = WorkerStateStore(
        tmp_path / "state" / "worker-status.json",
        stale_after_seconds=30,
    )
    runtime = WorkerRuntime(
        queue=queue,
        state_store=state_store,
        worker_id="worker-m4",
        database=database,
        result_store=result_store,
        diagnostic_runner=runner,
        lease_seconds=60,
        heartbeat_seconds=5,
        poll_seconds=0.01,
    )
    return database, queue, runtime, result_store


def test_worker_completes_diagnostic_with_result_and_leaves_analysis_queued(
    tmp_path: Path,
) -> None:
    database, queue, runtime, result_store = make_runtime(
        tmp_path,
        runner=SuccessfulRunner(),
    )
    historical = queue.create(TaskCreate(task_type="analysis", priority=1))
    task = queue.create(
        TaskCreate(
            task_type="system.diagnostic_snapshot",
            payload={
                "schema_version": "1.0",
                "sections": ["core", "worker", "queue"],
            },
            priority=50,
            timeout_seconds=30,
        )
    )

    cycle = runtime.run_once()

    assert cycle.processed is True
    assert cycle.succeeded is True
    completed = queue.get(task.task_id)
    assert completed.status is TaskStatus.COMPLETED
    assert completed.result_id is not None
    result_row = database.fetchone(
        "SELECT * FROM results WHERE result_id = ?",
        (completed.result_id,),
    )
    assert result_row is not None
    document = result_store.read_json(result_row["object_hash"], max_bytes=64 * 1024)
    assert document["schema_version"] == "1.0"
    assert queue.get(historical.task_id).status is TaskStatus.QUEUED
    assert runtime.supported_task_types == (
        "system.diagnostic_snapshot",
        "system.noop",
    )
    database.close()


def test_worker_cancellation_produces_cancelled_without_result(tmp_path: Path) -> None:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    queue = DiagnosticQueueRepository(database)
    result_store = ResultStore(tmp_path / "results")
    state_store = WorkerStateStore(tmp_path / "state.json", stale_after_seconds=30)
    task = queue.create(
        TaskCreate(
            task_type="system.diagnostic_snapshot",
            payload={"schema_version": "1.0", "sections": ["core"]},
            timeout_seconds=30,
        )
    )
    runtime = WorkerRuntime(
        queue=queue,
        state_store=state_store,
        worker_id="worker-m4",
        database=database,
        result_store=result_store,
        diagnostic_runner=CancellingRunner(lambda: queue.request_cancel(task.task_id)),
        lease_seconds=60,
        heartbeat_seconds=5,
    )

    cycle = runtime.run_once()

    assert cycle.succeeded is True
    cancelled = queue.get(task.task_id)
    assert cancelled.status is TaskStatus.CANCELLED
    assert cancelled.result_id is None
    assert database.fetchone(
        "SELECT result_id FROM results WHERE task_id = ?",
        (task.task_id,),
    ) is None
    database.close()


def test_cancel_arriving_during_result_commit_finishes_cancelled_without_result(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    queue = DiagnosticQueueRepository(database)
    task = queue.create(
        TaskCreate(
            task_type="system.diagnostic_snapshot",
            payload={"schema_version": "1.0", "sections": ["core"]},
            timeout_seconds=30,
        )
    )
    result_store = CancelOnPutResultStore(
        tmp_path / "results",
        lambda: queue.request_cancel(task.task_id),
    )
    runtime = WorkerRuntime(
        queue=queue,
        state_store=WorkerStateStore(
            tmp_path / "state.json",
            stale_after_seconds=30,
        ),
        worker_id="worker-m4",
        database=database,
        result_store=result_store,
        diagnostic_runner=SuccessfulRunner(),
        lease_seconds=60,
        heartbeat_seconds=5,
    )

    cycle = runtime.run_once()

    assert cycle.processed is True
    assert cycle.succeeded is True
    cancelled = queue.get(task.task_id)
    assert cancelled.status is TaskStatus.CANCELLED
    assert cancelled.result_id is None
    assert database.fetchone(
        "SELECT result_id FROM results WHERE task_id = ?",
        (task.task_id,),
    ) is None
    attempt = database.fetchone(
        "SELECT status, error_code FROM task_attempts WHERE task_id = ?",
        (task.task_id,),
    )
    assert attempt is not None
    assert attempt["status"] == TaskStatus.CANCELLED.value
    assert attempt["error_code"] == "WORKER_TASK_CANCELLED"
    database.close()


def test_worker_timeout_is_controlled_failure_and_returns_to_non_executing_state(
    tmp_path: Path,
) -> None:
    database, queue, runtime, _ = make_runtime(tmp_path, runner=TimeoutRunner())
    task = queue.create(
        TaskCreate(
            task_type="system.diagnostic_snapshot",
            payload={"schema_version": "1.0", "sections": ["worker"]},
            timeout_seconds=30,
        )
    )

    cycle = runtime.run_once()

    assert cycle.succeeded is False
    failed = queue.get(task.task_id)
    assert failed.status is TaskStatus.FAILED
    assert failed.error_code == "WORKER_TASK_TIMEOUT"
    assert failed.error_message == "诊断任务执行超时。"
    status = runtime.state_store.read_status(now=datetime.now(UTC))
    assert status.active_task_id is None
    assert status.state == "degraded"
    database.close()


def test_worker_rejects_invalid_diagnostic_payload_without_child_execution(
    tmp_path: Path,
) -> None:
    database, queue, runtime, _ = make_runtime(tmp_path, runner=SuccessfulRunner())
    task = queue.create(
        TaskCreate(
            task_type="system.diagnostic_snapshot",
            payload={"schema_version": "1.0", "sections": ["logs"]},
            timeout_seconds=30,
        )
    )

    cycle = runtime.run_once()

    assert cycle.succeeded is False
    failed = queue.get(task.task_id)
    assert failed.status is TaskStatus.FAILED
    assert failed.error_code == "DIAGNOSTIC_PAYLOAD_INVALID"
    assert failed.error_message == "诊断任务请求无效。"
    assert "logs" not in failed.error_message
    database.close()
