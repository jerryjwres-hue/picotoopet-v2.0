"""Worker 处理器封闭注册表。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from picotoopet_core.domain.models import TaskRecord


@dataclass(frozen=True, slots=True)
class HandlerResult:
    """处理器的确定性最小结果；本切片不写外部结果对象。"""

    summary: dict[str, Any]


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


def default_handlers() -> dict[str, WorkerHandler]:
    """返回显式冻结的处理器映射，不做动态发现。"""

    return {"system.noop": _system_noop}
