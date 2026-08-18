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
    if task.payload.get("raise_error") is True:
        raise RuntimeError("requested noop failure")
    return HandlerResult(
        summary={
            "task_type": task.task_type,
            "payload_keys": sorted(task.payload),
        }
    )


def _register_research_search_if_ready(handlers: dict[str, WorkerHandler]) -> None:
    """仅当独立 Gateway 的 search 依赖健康时才把 research.search 暴露给队列。"""

    # 延迟导入：保持 Worker 基础模块不依赖 Research Gateway 外部工具链。
    from picotoopet_core.research.execution import (
        ResearchGatewayExecutor,
        ResearchSearchCoordinator,
    )

    executor = ResearchGatewayExecutor()
    if not executor.search_ready():
        return
    coordinator = ResearchSearchCoordinator(executor)
    handlers[ResearchSearchCoordinator.TASK_TYPE] = coordinator.handler


def default_handlers(
    diagnostic_handler: WorkerHandler | None = None,
    provider_handler: WorkerHandler | None = None,
    local_intelligence_handler: WorkerHandler | None = None,
) -> dict[str, WorkerHandler]:
    """返回显式冻结的处理器映射，不做动态插件发现。"""

    handlers: dict[str, WorkerHandler] = {"system.noop": _system_noop}
    if diagnostic_handler is not None:
        handlers["system.diagnostic_snapshot"] = diagnostic_handler
    if provider_handler is not None:
        handlers["provider.codex.handoff-v1"] = provider_handler
    if local_intelligence_handler is not None:
        # 本地模型只有显式注入时才认领固定任务，避免 Ollama 未就绪时误领队列。
        handlers["autonomous.local_analysis.v1"] = local_intelligence_handler

    # Research 不是插件发现：只探测一个固定安装路径/固定环境覆盖与固定能力。
    _register_research_search_if_ready(handlers)
    return handlers
