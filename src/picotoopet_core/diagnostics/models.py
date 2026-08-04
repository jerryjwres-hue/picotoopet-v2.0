"""Slice D 系统诊断快照严格合同。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DiagnosticSection = Literal["core", "worker", "queue"]
DiagnosticStatus = Literal["pass", "warn", "fail"]
DiagnosticCheckName = Literal[
    "core_health",
    "worker_heartbeat",
    "queue_backlog",
]
DiagnosticReasonCode = Literal[
    "CORE_HEALTHY",
    "CORE_DEGRADED",
    "WORKER_ONLINE",
    "WORKER_OFFLINE",
    "WORKER_STALE",
    "QUEUE_HEALTHY",
    "QUEUE_BACKLOG",
    "QUEUE_OLD",
]
DiagnosticWarning = Literal[
    "CORE_DEGRADED",
    "WORKER_OFFLINE",
    "WORKER_STALE",
    "QUEUE_BACKLOG",
    "QUEUE_OLD",
]

_SECTION_ORDER: tuple[DiagnosticSection, ...] = ("core", "worker", "queue")
_PUBLIC_STATUSES: frozenset[str] = frozenset(
    {
        "Created",
        "Validating",
        "Queued",
        "Running",
        "WaitingForTool",
        "WaitingForApproval",
        "Retrying",
        "Completed",
        "Failed",
        "Cancelled",
        "Archived",
    }
)
_ALLOWED_CHECK_COMBINATIONS: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("core_health", "pass", "CORE_HEALTHY"),
        ("core_health", "warn", "CORE_DEGRADED"),
        ("core_health", "fail", "CORE_DEGRADED"),
        ("worker_heartbeat", "pass", "WORKER_ONLINE"),
        ("worker_heartbeat", "warn", "WORKER_STALE"),
        ("worker_heartbeat", "fail", "WORKER_OFFLINE"),
        ("queue_backlog", "pass", "QUEUE_HEALTHY"),
        ("queue_backlog", "warn", "QUEUE_BACKLOG"),
        ("queue_backlog", "warn", "QUEUE_OLD"),
    }
)


class _StrictModel(BaseModel):
    """禁止未知字段并冻结解析后的诊断合同。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DiagnosticSnapshotRequest(_StrictModel):
    """Windows 可提交的固定诊断请求。"""

    schema_version: Literal["1.0"] = "1.0"
    sections: tuple[DiagnosticSection, ...] = _SECTION_ORDER

    @field_validator("sections")
    @classmethod
    def _normalize_sections(
        cls,
        sections: tuple[DiagnosticSection, ...],
    ) -> tuple[DiagnosticSection, ...]:
        if not sections:
            raise ValueError("sections 不能为空。")
        if len(set(sections)) != len(sections):
            raise ValueError("sections 不允许重复。")
        selected = set(sections)
        return tuple(section for section in _SECTION_ORDER if section in selected)


class DiagnosticFacts(_StrictModel):
    """父 Worker 预先裁剪的唯一子进程输入。"""

    core_version: str = Field(min_length=1, max_length=64)
    core_health_state: Literal["online", "degraded", "offline"]
    database_schema_version: int = Field(ge=0, le=10000)
    worker_id: str | None = Field(default=None, max_length=128)
    worker_state: Literal["starting", "online", "degraded", "offline"]
    worker_reason: str = Field(min_length=1, max_length=100)
    worker_supported_task_types: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    worker_last_heartbeat_at: datetime | None = None
    queue_counts: dict[str, int]
    oldest_queued_age_seconds: int | None = Field(default=None, ge=0, le=315360000)

    @field_validator("worker_supported_task_types")
    @classmethod
    def _normalize_supported_task_types(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("worker_supported_task_types 不允许重复。")
        for value in values:
            if not value or len(value) > 100:
                raise ValueError("worker_supported_task_types 包含非法值。")
        return tuple(sorted(values))

    @field_validator("queue_counts")
    @classmethod
    def _validate_queue_counts(cls, counts: dict[str, int]) -> dict[str, int]:
        return _normalize_counts(counts)


class DiagnosticCoreSnapshot(_StrictModel):
    """Mac Core 非敏感公开状态。"""

    version: str = Field(min_length=1, max_length=64)
    health_state: Literal["online", "degraded", "offline"]
    database_schema_version: int = Field(ge=0, le=10000)


class DiagnosticWorkerSnapshot(_StrictModel):
    """Worker 公共心跳状态，不包含路径或原始错误。"""

    worker_id: str | None = Field(default=None, max_length=128)
    state: Literal["starting", "online", "degraded", "offline"]
    reason: str = Field(min_length=1, max_length=100)
    supported_task_types: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    last_heartbeat_at: datetime | None = None

    @field_validator("supported_task_types")
    @classmethod
    def _normalize_task_types(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("supported_task_types 不允许重复。")
        for value in values:
            if not value or len(value) > 100:
                raise ValueError("supported_task_types 包含非法值。")
        return tuple(sorted(values))


class DiagnosticQueueSnapshot(_StrictModel):
    """队列聚合，只暴露公开状态计数和最老排队年龄。"""

    counts: dict[str, int]
    oldest_queued_age_seconds: int | None = Field(default=None, ge=0, le=315360000)

    @field_validator("counts")
    @classmethod
    def _validate_counts(cls, counts: dict[str, int]) -> dict[str, int]:
        return _normalize_counts(counts)


class DiagnosticCheck(_StrictModel):
    """固定诊断检查项。"""

    name: DiagnosticCheckName
    status: DiagnosticStatus
    reason_code: DiagnosticReasonCode


class DiagnosticSnapshotResult(_StrictModel):
    """最终可持久化、可由 Windows 固定卡片渲染的结果。"""

    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    core: DiagnosticCoreSnapshot | None = None
    worker: DiagnosticWorkerSnapshot | None = None
    queue: DiagnosticQueueSnapshot | None = None
    checks: tuple[DiagnosticCheck, ...]
    warnings: tuple[DiagnosticWarning, ...] = ()

    @field_validator("checks")
    @classmethod
    def _validate_checks(
        cls,
        checks: tuple[DiagnosticCheck, ...],
    ) -> tuple[DiagnosticCheck, ...]:
        if not checks:
            raise ValueError("checks 不能为空。")
        names = [check.name for check in checks]
        if len(set(names)) != len(names):
            raise ValueError("checks 不允许重复。")
        order = {"core_health": 0, "worker_heartbeat": 1, "queue_backlog": 2}
        return tuple(sorted(checks, key=lambda check: order[check.name]))

    @field_validator("warnings")
    @classmethod
    def _normalize_warnings(
        cls,
        warnings: tuple[DiagnosticWarning, ...],
    ) -> tuple[DiagnosticWarning, ...]:
        if len(set(warnings)) != len(warnings):
            raise ValueError("warnings 不允许重复。")
        return tuple(sorted(warnings))

    @model_validator(mode="after")
    def _validate_cards_and_checks(self) -> DiagnosticSnapshotResult:
        expected_checks: set[str] = set()
        if self.core is not None:
            expected_checks.add("core_health")
        if self.worker is not None:
            expected_checks.add("worker_heartbeat")
        if self.queue is not None:
            expected_checks.add("queue_backlog")

        actual_checks = {check.name for check in self.checks}
        if actual_checks != expected_checks:
            raise ValueError("每张诊断结果卡片必须且只能对应一个固定检查项。")
        for check in self.checks:
            combination = (check.name, check.status, check.reason_code)
            if combination not in _ALLOWED_CHECK_COMBINATIONS:
                raise ValueError("诊断检查状态与原因码不符合固定合同。")
        return self


def _normalize_counts(counts: dict[str, int]) -> dict[str, int]:
    unknown = set(counts) - _PUBLIC_STATUSES
    if unknown:
        raise ValueError("counts 包含未知任务状态。")
    for value in counts.values():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("counts 必须是非负整数。")
    return {key: counts[key] for key in sorted(counts)}
