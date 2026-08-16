"""Mac Worker 到独立 Research Gateway 的封闭 subprocess 接线。"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.worker.handlers import HandlerResult

from .models import ResearchSearchRequest, ResearchSearchResult

_MAX_GATEWAY_ENVELOPE_BYTES = 64 * 1024
_MAX_RESEARCH_OUTPUT_BYTES = 48 * 1024
_DEFAULT_GATEWAY = Path(
    "~/Library/Application Support/PicotooPet/ResearchGateway/bin/"
    "picotoopet-research-gateway"
).expanduser()


class ResearchGatewayExecutionError(RuntimeError):
    """Research Gateway 不可用、失败或返回不可信结果。"""


@dataclass(frozen=True, slots=True)
class GatewayProcessResult:
    """可注入测试的最小进程结果。"""

    returncode: int
    stdout: str
    stderr: str


ProcessRunner = Callable[[list[str], int], GatewayProcessResult]


def _run_process(argv: list[str], timeout_seconds: int) -> GatewayProcessResult:
    """仅执行受信 argv；明确不启用 shell。"""

    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        # 错误边界：不给 Core/Windows 暴露工具 stderr、路径细节或凭据片段。
        raise ResearchGatewayExecutionError("gateway process unavailable") from error
    return GatewayProcessResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


class ResearchGatewayExecutor:
    """只允许调用独立 Gateway 的 research.search 能力。"""

    def __init__(
        self,
        *,
        executable: Path | None = None,
        process: ProcessRunner = _run_process,
    ) -> None:
        configured = os.environ.get("PICOTOOPET_RESEARCH_GATEWAY", "").strip()
        self.executable = Path(configured).expanduser() if configured else executable or _DEFAULT_GATEWAY
        self._process = process

    def search(self, *, query: str, limit: int, timeout_seconds: int) -> ResearchSearchResult:
        # 参数再次走固定 Pydantic 合同，防止 Worker 直接透传任意 Gateway 参数。
        request = ResearchSearchRequest(query=query, limit=limit)
        params_json = json.dumps(
            {"query": request.query, "limit": request.limit},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        process_result = self._process(
            [
                str(self.executable),
                "--capability",
                "research.search",
                "--params-json",
                params_json,
            ],
            min(max(int(timeout_seconds), 1), 120),
        )
        if process_result.returncode != 0:
            raise ResearchGatewayExecutionError("gateway process failed")
        if len(process_result.stdout.encode("utf-8")) > _MAX_GATEWAY_ENVELOPE_BYTES:
            raise ResearchGatewayExecutionError("gateway response exceeded safe limit")

        try:
            envelope = json.loads(process_result.stdout)
        except (TypeError, json.JSONDecodeError) as error:
            raise ResearchGatewayExecutionError("gateway response was invalid") from error
        if not isinstance(envelope, dict) or envelope.get("returncode") != 0:
            raise ResearchGatewayExecutionError("gateway command failed")
        output = envelope.get("stdout")
        if not isinstance(output, str):
            raise ResearchGatewayExecutionError("gateway response was invalid")
        if len(output.encode("utf-8")) > _MAX_RESEARCH_OUTPUT_BYTES:
            raise ResearchGatewayExecutionError("research result exceeded safe limit")

        return ResearchSearchResult(
            query=request.query,
            limit=request.limit,
            output=output,
        )

    def search_ready(self) -> bool:
        """只探测 research.search 所需的 Gateway/read-only/mcporter 条件。"""

        if not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            return False
        try:
            result = self._process([str(self.executable), "--health"], 10)
            if result.returncode != 0 or len(result.stdout.encode("utf-8")) > 16 * 1024:
                return False
            health = json.loads(result.stdout)
        except (ResearchGatewayExecutionError, json.JSONDecodeError, TypeError):
            return False
        tools = health.get("tools") if isinstance(health, dict) else None
        return bool(
            isinstance(health, dict)
            and health.get("read_only") is True
            and health.get("xiaoyuzhou_enabled") is False
            and isinstance(tools, dict)
            and tools.get("mcporter") is True
        )


class ResearchSearchCoordinator:
    """把固定队列任务翻译成 Research Gateway 搜索并返回 ResultStore 文档。"""

    TASK_TYPE = "research.search"
    CAPABILITY = "research.search"

    def __init__(self, executor: ResearchGatewayExecutor) -> None:
        self.executor = executor

    def handler(self, task: TaskRecord) -> HandlerResult:
        if task.task_type != self.TASK_TYPE:
            raise ResearchGatewayExecutionError("unsupported research task type")
        try:
            request = ResearchSearchRequest.model_validate(task.payload)
        except ValidationError as error:
            raise ResearchGatewayExecutionError("research search payload invalid") from error
        result = self.executor.search(
            query=request.query,
            limit=request.limit,
            timeout_seconds=task.timeout_seconds,
        )
        return HandlerResult(
            summary={
                "task_type": task.task_type,
                "capability": self.CAPABILITY,
                "query_length": len(request.query),
            },
            result_document=result.model_dump(mode="json"),
            result_type=self.TASK_TYPE,
            schema_version=result.schema_version,
        )
