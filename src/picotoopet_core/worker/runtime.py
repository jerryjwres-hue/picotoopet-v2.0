"""独立 Mac Worker Runtime。"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from threading import Event, Thread

from picotoopet_core.queue.repository import LeaseOwnershipError, QueueRepository

from .handlers import WorkerHandler, default_handlers
from .state import WorkerStateStore


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

    def __exit__(self, exc_type, exc, traceback) -> None:
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
        self.queue = queue
        self.state_store = state_store
        self.worker_id = worker_id
        self.handlers = dict(handlers or default_handlers())
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.poll_seconds = poll_seconds

    @property
    def supported_task_types(self) -> tuple[str, ...]:
        """返回稳定排序的封闭任务类型集合。"""

        return tuple(sorted(self.handlers))

    def run_once(self) -> WorkerCycleResult:
        """恢复过期租约，并最多处理一个明确支持的任务。"""

        self.queue.recover_expired_leases()
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
                handler(task)
                heartbeat.raise_if_failed()
            self.queue.complete_leased(task.task_id, worker_id=self.worker_id)
        except Exception:
            with suppress(LeaseOwnershipError):
                self.queue.fail_leased(
                    task.task_id,
                    worker_id=self.worker_id,
                    error_code="WORKER_HANDLER_ERROR",
                    error_message=f"{task.task_type} handler failed",
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

    def _publish(self, *, state: str, reason: str, active_task_id: str | None) -> None:
        self.state_store.publish(
            state=state,
            reason=reason,
            worker_id=self.worker_id,
            supported_task_types=self.supported_task_types,
            active_task_id=active_task_id,
        )
