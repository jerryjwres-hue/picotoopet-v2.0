"""独立 Mac Worker Runtime。"""

from __future__ import annotations

import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread

from pydantic import ValidationError

from picotoopet_core import __version__
from picotoopet_core.db.database import Database
from picotoopet_core.diagnostics.models import (
    DiagnosticFacts,
    DiagnosticSnapshotRequest,
    DiagnosticSnapshotResult,
)
from picotoopet_core.diagnostics.subprocess_runner import (
    DiagnosticCancelledError,
    DiagnosticCollectionError,
    DiagnosticResultInvalidError,
    DiagnosticSubprocessRunner,
    DiagnosticTimeoutError,
)
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.queue.repository import LeaseOwnershipError, QueueRepository
from picotoopet_core.results.store import ResultStore, ResultTooLargeError

from .handlers import HandlerResult, WorkerHandler, default_handlers
from .state import WorkerStateStore

_MAX_DIAGNOSTIC_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class WorkerCycleResult:
    """一次 Worker 循环的稳定结果。"""

    processed: bool
    succeeded: bool
    task_id: str | None = None


class LeaseHeartbeat:
    """处理器运行期间按固定间隔续租，并保存后台错误。"""

    def __init__(
        self,
        *,
        queue: QueueRepository,
        task_id: str,
        worker_id: str,
        lease_seconds: int,
        heartbeat_seconds: int,
    ) -> None:
        if heartbeat_seconds < 1:
            raise ValueError("heartbeat_seconds 必须大于 0。")
        if heartbeat_seconds >= lease_seconds:
            raise ValueError("heartbeat_seconds 必须小于 lease_seconds。")
        self.queue = queue
        self.task_id = task_id
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self._stop = Event()
        self._thread: Thread | None = None
        self._error: Exception | None = None

    def __enter__(self) -> LeaseHeartbeat:
        self._thread = Thread(
            target=self._run,
            name=f"picotoopet-lease-heartbeat-{self.task_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # type: ignore[no-untyped-def]
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1, self.heartbeat_seconds + 1))

    def _run(self) -> None:
        while not self._stop.wait(self.heartbeat_seconds):
            try:
                self.queue.renew_lease(
                    self.task_id,
                    worker_id=self.worker_id,
                    lease_seconds=self.lease_seconds,
                )
            except Exception as error:  # 后台线程把错误交回主执行路径。
                self._error = error
                self._stop.set()
                return

    def raise_if_failed(self) -> None:
        """把续租失败重新抛到 Worker 主循环。"""

        if self._error is not None:
            raise self._error


class WorkerRuntime:
    """只领取显式注册任务类型的单进程 Worker。"""

    def __init__(
        self,
        *,
        queue: QueueRepository,
        state_store: WorkerStateStore,
        worker_id: str,
        handlers: dict[str, WorkerHandler] | None = None,
        database: Database | None = None,
        result_store: ResultStore | None = None,
        diagnostic_runner: DiagnosticSubprocessRunner | None = None,
        lease_seconds: int = 60,
        heartbeat_seconds: int = 15,
        poll_seconds: float = 2.0,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id 不能为空。")
        if lease_seconds < 2:
            raise ValueError("lease_seconds 必须至少为 2。")
        if poll_seconds <= 0:
            raise ValueError("poll_seconds 必须大于 0。")
        if (database is None) != (result_store is None):
            raise ValueError("database 与 result_store 必须同时提供。")
        if database is not None and not isinstance(queue, DiagnosticQueueRepository):
            raise TypeError("诊断 Worker 必须使用 DiagnosticQueueRepository。")

        self.queue = queue
        self.state_store = state_store
        self.worker_id = worker_id
        self.database = database
        self.result_store = result_store
        self.diagnostic_runner = diagnostic_runner or DiagnosticSubprocessRunner()
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.poll_seconds = poll_seconds
        diagnostic_handler = self._handle_diagnostic if database is not None else None
        self.handlers = dict(handlers or default_handlers(diagnostic_handler))

    @property
    def supported_task_types(self) -> tuple[str, ...]:
        """返回稳定排序的封闭任务类型集合。"""

        return tuple(sorted(self.handlers))

    def run_once(self) -> WorkerCycleResult:
        """恢复过期租约，并最多处理一个明确支持的任务。"""

        self.queue.recover_expired_leases()
        if isinstance(self.queue, DiagnosticQueueRepository):
            self.queue.promote_retries(
                supported_task_types=self.supported_task_types,
                limit=100,
            )
        self._publish(state="online", reason="idle", active_task_id=None)
        task = self.queue.lease_next(
            self.worker_id,
            lease_seconds=self.lease_seconds,
            supported_task_types=self.supported_task_types,
        )
        if task is None:
            return WorkerCycleResult(processed=False, succeeded=True)

        self._publish(state="online", reason="executing", active_task_id=task.task_id)
        handler = self.handlers[task.task_type]
        try:
            with LeaseHeartbeat(
                queue=self.queue,
                task_id=task.task_id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                heartbeat_seconds=self.heartbeat_seconds,
            ) as heartbeat:
                handler_result = handler(task)
                heartbeat.raise_if_failed()

            if self._cancel_requested(task.task_id):
                return self._finish_cancelled(task)
            if handler_result.result_document is None:
                self.queue.complete_leased(task.task_id, worker_id=self.worker_id)
            else:
                self._commit_result(task, handler_result)
        except DiagnosticCancelledError:
            return self._finish_cancelled(task)
        except ValidationError:
            return self._finish_failed(
                task,
                error_code="DIAGNOSTIC_PAYLOAD_INVALID",
                error_message="诊断任务请求无效。",
            )
        except DiagnosticTimeoutError:
            return self._finish_failed(
                task,
                error_code="WORKER_TASK_TIMEOUT",
                error_message="诊断任务执行超时。",
            )
        except DiagnosticResultInvalidError:
            return self._finish_failed(
                task,
                error_code="DIAGNOSTIC_RESULT_INVALID",
                error_message="诊断结果合同无效。",
            )
        except ResultTooLargeError:
            return self._finish_failed(
                task,
                error_code="DIAGNOSTIC_RESULT_TOO_LARGE",
                error_message="诊断结果超过大小上限。",
            )
        except DiagnosticCollectionError:
            return self._finish_failed(
                task,
                error_code="DIAGNOSTIC_COLLECTION_FAILED",
                error_message="诊断采集失败。",
            )
        except LeaseOwnershipError:
            self._publish(
                state="degraded",
                reason="worker_lease_lost",
                active_task_id=None,
            )
            return WorkerCycleResult(
                processed=True,
                succeeded=False,
                task_id=task.task_id,
            )
        except Exception:
            code = (
                "DIAGNOSTIC_COLLECTION_FAILED"
                if task.task_type == "system.diagnostic_snapshot"
                else "WORKER_HANDLER_ERROR"
            )
            message = (
                "诊断采集失败。"
                if task.task_type == "system.diagnostic_snapshot"
                else f"{task.task_type} handler failed"
            )
            return self._finish_failed(
                task,
                error_code=code,
                error_message=message,
            )

        self._publish(state="online", reason="idle", active_task_id=None)
        return WorkerCycleResult(
            processed=True,
            succeeded=True,
            task_id=task.task_id,
        )

    def run_loop(self, stop_event: Event) -> None:
        """持续轮询，直到调用方发出停止信号。"""

        self._publish(state="starting", reason="worker_starting", active_task_id=None)
        try:
            while not stop_event.is_set():
                result = self.run_once()
                if not result.processed:
                    stop_event.wait(self.poll_seconds)
        finally:
            self._publish(state="offline", reason="worker_stopped", active_task_id=None)

    def _handle_diagnostic(self, task: TaskRecord) -> HandlerResult:
        if self.database is None or self.result_store is None:
            raise RuntimeError("诊断依赖未装配。")
        request = DiagnosticSnapshotRequest.model_validate(task.payload)
        facts = self._build_diagnostic_facts()
        work_root = self.result_store.root / ".diagnostic-work"
        work_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="task-", dir=work_root) as temporary:
            candidate_path = self.diagnostic_runner.run(
                request,
                facts,
                output_dir=Path(temporary),
                timeout_seconds=min(float(task.timeout_seconds), 30.0),
                cancel_requested=lambda: self._cancel_requested(task.task_id),
            )
            result = DiagnosticSnapshotResult.model_validate_json(
                candidate_path.read_bytes()
            )
        return HandlerResult(
            summary={
                "task_type": task.task_type,
                "checks": len(result.checks),
                "warnings": len(result.warnings),
            },
            result_document=result.model_dump(mode="json"),
            result_type="system.diagnostic_snapshot",
            schema_version=result.schema_version,
        )

    def _build_diagnostic_facts(self) -> DiagnosticFacts:
        assert self.database is not None
        now = datetime.now(UTC)
        schema_version = int(
            self.database.scalar(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            )
            or 0
        )
        counts = {
            row["status"]: int(row["count"])
            for row in self.database.fetchall(
                "SELECT status, COUNT(*) AS count FROM tasks GROUP BY status"
            )
        }
        oldest_row = self.database.fetchone(
            "SELECT created_at FROM tasks WHERE status = ? "
            "ORDER BY created_at ASC LIMIT 1",
            (TaskStatus.QUEUED.value,),
        )
        oldest_age = None
        if oldest_row is not None:
            oldest_age = max(
                0,
                int(
                    (
                        now - datetime.fromisoformat(oldest_row["created_at"])
                    ).total_seconds()
                ),
            )
        return DiagnosticFacts(
            core_version=__version__,
            core_health_state="online",
            database_schema_version=schema_version,
            worker_id=self.worker_id,
            worker_state="online",
            worker_reason="executing",
            worker_supported_task_types=self.supported_task_types,
            worker_last_heartbeat_at=now,
            queue_counts=counts,
            oldest_queued_age_seconds=oldest_age,
        )

    def _commit_result(
        self,
        task: TaskRecord,
        handler_result: HandlerResult,
    ) -> None:
        if not isinstance(self.queue, DiagnosticQueueRepository):
            raise RuntimeError("诊断结果队列未装配。")
        if self.result_store is None:
            raise RuntimeError("ResultStore 未装配。")
        if handler_result.result_type is None or handler_result.schema_version is None:
            raise DiagnosticResultInvalidError("诊断结果元数据缺失。")
        assert handler_result.result_document is not None
        stored = self.result_store.put_json(
            handler_result.result_document,
            result_type=handler_result.result_type,
            max_bytes=_MAX_DIAGNOSTIC_BYTES,
        )
        self.queue.complete_leased_with_result(
            task.task_id,
            worker_id=self.worker_id,
            stored_result=stored,
            schema_version=handler_result.schema_version,
        )

    def _cancel_requested(self, task_id: str) -> bool:
        if not isinstance(self.queue, DiagnosticQueueRepository):
            return False
        return self.queue.is_cancel_requested(task_id, worker_id=self.worker_id)

    def _finish_cancelled(self, task: TaskRecord) -> WorkerCycleResult:
        if not isinstance(self.queue, DiagnosticQueueRepository):
            return self._finish_failed(
                task,
                error_code="WORKER_TASK_CANCELLED",
                error_message="任务已取消。",
            )
        try:
            self.queue.cancel_leased(task.task_id, worker_id=self.worker_id)
        except LeaseOwnershipError:
            current = self.queue.get(task.task_id)
            if current.status is not TaskStatus.CANCELLED:
                self._publish(
                    state="degraded",
                    reason="worker_lease_lost",
                    active_task_id=None,
                )
                return WorkerCycleResult(
                    processed=True,
                    succeeded=False,
                    task_id=task.task_id,
                )
        self._publish(state="online", reason="idle", active_task_id=None)
        return WorkerCycleResult(
            processed=True,
            succeeded=True,
            task_id=task.task_id,
        )

    def _finish_failed(
        self,
        task: TaskRecord,
        *,
        error_code: str,
        error_message: str,
    ) -> WorkerCycleResult:
        with suppress(LeaseOwnershipError):
            self.queue.fail_leased(
                task.task_id,
                worker_id=self.worker_id,
                error_code=error_code,
                error_message=error_message,
            )
        self._publish(
            state="degraded",
            reason="task_execution_failed",
            active_task_id=None,
        )
        return WorkerCycleResult(
            processed=True,
            succeeded=False,
            task_id=task.task_id,
        )

    def _publish(self, *, state: str, reason: str, active_task_id: str | None) -> None:
        self.state_store.publish(
            state=state,
            reason=reason,
            worker_id=self.worker_id,
            supported_task_types=self.supported_task_types,
            active_task_id=active_task_id,
        )
