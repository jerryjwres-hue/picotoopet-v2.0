"""Worker 处理器封闭注册表。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from picotoopet_core.domain.models import TaskRecord


@dataclass(frozen=True, slots=True)
class HandlerResult:
    """处理器的确定性结果；父 Runtime 仍拥有持久化和终态。"""

    summary: dict[str, Any]
    result_document: dict[str, Any] | None = None
    result_type: str | None = None
    schema_version: str | None = None


WorkerHandler = Callable[[TaskRecord], HandlerResult]


def _system_noop(task: TaskRecord) -> HandlerResult:
    """无网络、无文件和无模型副作用的基础处理器。"""

    if task.payload.get("raise_error") is True:
        raise RuntimeError("requested noop failure")
    return HandlerResult(
        summary={
            "task_type": task.task_type,
            "payload_keys": sorted(task.payload),
        }
    )


def default_handlers(
    diagnostic_handler: WorkerHandler | None = None,
) -> dict[str, WorkerHandler]:
    """返回显式冻结的处理器映射，不做动态发现。"""

    handlers: dict[str, WorkerHandler] = {"system.noop": _system_noop}
    if diagnostic_handler is not None:
        handlers["system.diagnostic_snapshot"] = diagnostic_handler
    return handlers
