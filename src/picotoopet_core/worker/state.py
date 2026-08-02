"""Worker 状态文件的原子写入和保守读取。"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from picotoopet_core.api.contracts import WorkerStatusResponse


DEFAULT_WORKER_STATUS_FILENAME = "worker-status.json"


class WorkerStateStore:
    """在 API 与独立 Worker 进程之间交换只读状态快照。"""

    def __init__(self, path: Path, *, stale_after_seconds: int = 45) -> None:
        if stale_after_seconds < 1:
            raise ValueError("stale_after_seconds 必须大于 0。")
        self.path = path
        self.stale_after = timedelta(seconds=stale_after_seconds)

    def publish(
        self,
        *,
        state: str,
        reason: str,
        worker_id: str,
        supported_task_types: tuple[str, ...],
        active_task_id: str | None,
        observed_at: datetime | None = None,
    ) -> WorkerStatusResponse:
        """使用临时文件和原子替换写入完整状态。"""

        now = observed_at or datetime.now(UTC)
        snapshot = WorkerStatusResponse(
            available=state == "online",
            state=state,
            reason=reason,
            worker_id=worker_id,
            supported_task_types=list(supported_task_types),
            active_task_id=active_task_id,
            last_heartbeat_at=now,
            observed_at=now,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                snapshot.model_dump_json(indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return snapshot

    def read_status(self, *, now: datetime | None = None) -> WorkerStatusResponse:
        """读取快照并把缺失、损坏或过期状态保守降级。"""

        checked_at = now or datetime.now(UTC)
        if not self.path.exists():
            return WorkerStatusResponse(observed_at=checked_at)
        try:
            snapshot = WorkerStatusResponse.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValidationError, ValueError):
            return WorkerStatusResponse(
                state="degraded",
                reason="worker_status_corrupt",
                observed_at=checked_at,
            )

        heartbeat = snapshot.last_heartbeat_at or snapshot.observed_at
        if snapshot.state in {"online", "starting"} and checked_at - heartbeat > self.stale_after:
            return snapshot.model_copy(
                update={
                    "available": False,
                    "state": "offline",
                    "reason": "worker_heartbeat_stale",
                    "active_task_id": None,
                    "observed_at": checked_at,
                }
            )
        return snapshot.model_copy(update={"observed_at": checked_at})
