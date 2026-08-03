"""只从预裁剪事实生成固定诊断结果。"""

from __future__ import annotations

from datetime import UTC, datetime

from .models import (
    DiagnosticCheck,
    DiagnosticCoreSnapshot,
    DiagnosticFacts,
    DiagnosticQueueSnapshot,
    DiagnosticSnapshotRequest,
    DiagnosticSnapshotResult,
    DiagnosticWarning,
    DiagnosticWorkerSnapshot,
)

_QUEUE_BACKLOG_THRESHOLD = 100
_QUEUE_OLD_SECONDS = 300


def collect_snapshot(
    request: DiagnosticSnapshotRequest,
    facts: DiagnosticFacts,
) -> DiagnosticSnapshotResult:
    """生成白名单诊断卡片；不访问网络、环境、日志或文件树。"""

    core: DiagnosticCoreSnapshot | None = None
    worker: DiagnosticWorkerSnapshot | None = None
    queue: DiagnosticQueueSnapshot | None = None
    checks: list[DiagnosticCheck] = []
    warnings: set[DiagnosticWarning] = set()

    if "core" in request.sections:
        core = DiagnosticCoreSnapshot(
            version=facts.core_version,
            health_state=facts.core_health_state,
            database_schema_version=facts.database_schema_version,
        )
        if facts.core_health_state == "online":
            checks.append(
                DiagnosticCheck(
                    name="core_health",
                    status="pass",
                    reason_code="CORE_HEALTHY",
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    name="core_health",
                    status="fail" if facts.core_health_state == "offline" else "warn",
                    reason_code="CORE_DEGRADED",
                )
            )
            warnings.add("CORE_DEGRADED")

    if "worker" in request.sections:
        worker = DiagnosticWorkerSnapshot(
            worker_id=facts.worker_id,
            state=facts.worker_state,
            reason=facts.worker_reason,
            supported_task_types=facts.worker_supported_task_types,
            last_heartbeat_at=facts.worker_last_heartbeat_at,
        )
        if facts.worker_state == "online":
            checks.append(
                DiagnosticCheck(
                    name="worker_heartbeat",
                    status="pass",
                    reason_code="WORKER_ONLINE",
                )
            )
        elif facts.worker_state == "offline":
            checks.append(
                DiagnosticCheck(
                    name="worker_heartbeat",
                    status="fail",
                    reason_code="WORKER_OFFLINE",
                )
            )
            warnings.add("WORKER_OFFLINE")
        else:
            checks.append(
                DiagnosticCheck(
                    name="worker_heartbeat",
                    status="warn",
                    reason_code="WORKER_STALE",
                )
            )
            warnings.add("WORKER_STALE")

    if "queue" in request.sections:
        queue = DiagnosticQueueSnapshot(
            counts=facts.queue_counts,
            oldest_queued_age_seconds=facts.oldest_queued_age_seconds,
        )
        queued = facts.queue_counts.get("Queued", 0)
        oldest = facts.oldest_queued_age_seconds
        if queued > _QUEUE_BACKLOG_THRESHOLD:
            checks.append(
                DiagnosticCheck(
                    name="queue_backlog",
                    status="warn",
                    reason_code="QUEUE_BACKLOG",
                )
            )
            warnings.add("QUEUE_BACKLOG")
        elif oldest is not None and oldest > _QUEUE_OLD_SECONDS:
            checks.append(
                DiagnosticCheck(
                    name="queue_backlog",
                    status="warn",
                    reason_code="QUEUE_OLD",
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    name="queue_backlog",
                    status="pass",
                    reason_code="QUEUE_HEALTHY",
                )
            )
        if oldest is not None and oldest > _QUEUE_OLD_SECONDS:
            warnings.add("QUEUE_OLD")

    return DiagnosticSnapshotResult(
        generated_at=datetime.now(UTC),
        core=core,
        worker=worker,
        queue=queue,
        checks=tuple(checks),
        warnings=tuple(warnings),
    )
