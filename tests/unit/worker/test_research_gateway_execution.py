"""Mac Worker → 独立 Research Gateway 进程的封闭执行契约。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.research.execution import (
    GatewayProcessResult,
    ResearchGatewayExecutionError,
    ResearchGatewayExecutor,
    ResearchSearchCoordinator,
)


class RecordingProcess:
    def __init__(self, result: GatewayProcessResult) -> None:
        # 调用记录：测试必须证明 Worker 只传结构化 argv，不拼 shell 命令。
        self.result = result
        self.calls: list[tuple[list[str], int]] = []

    def __call__(self, argv: list[str], timeout_seconds: int) -> GatewayProcessResult:
        self.calls.append((argv, timeout_seconds))
        return self.result


def _task(task_id: str = "task-research-001") -> TaskRecord:
    return TaskRecord.model_validate(
        {
            "task_id": task_id,
            "task_type": "research.search",
            "status": "Running",
            "priority": 60,
            "resource_tag": "research-gateway",
            "payload": {"schema_version": "1.0", "query": "OpenAI", "limit": 5},
            "result_id": None,
            "attempt_count": 1,
            "max_attempts": 2,
            "timeout_seconds": 120,
            "created_at": "2026-08-15T00:00:00Z",
            "updated_at": "2026-08-15T00:00:00Z",
        }
    )


def test_executor_uses_only_installed_gateway_argv(tmp_path: Path) -> None:
    executable = tmp_path / "picotoopet-research-gateway"
    executable.write_text("fixture", encoding="utf-8")
    executable.chmod(0o755)
    process = RecordingProcess(
        GatewayProcessResult(
            returncode=0,
            stdout=json.dumps(
                {"returncode": 0, "stdout": "result-a\nresult-b", "stderr": ""}
            ),
            stderr="",
        )
    )
    executor = ResearchGatewayExecutor(executable=executable, process=process)

    result = executor.search(query="OpenAI", limit=5, timeout_seconds=120)

    assert result.output == "result-a\nresult-b"
    assert process.calls == [
        (
            [
                str(executable),
                "--capability",
                "research.search",
                "--params-json",
                json.dumps(
                    {"query": "OpenAI", "limit": 5},
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            ],
            120,
        )
    ]


def test_coordinator_returns_existing_result_store_document(tmp_path: Path) -> None:
    executable = tmp_path / "picotoopet-research-gateway"
    executable.write_text("fixture", encoding="utf-8")
    executable.chmod(0o755)
    process = RecordingProcess(
        GatewayProcessResult(
            returncode=0,
            stdout=json.dumps({"returncode": 0, "stdout": "search-output", "stderr": ""}),
            stderr="",
        )
    )
    coordinator = ResearchSearchCoordinator(
        ResearchGatewayExecutor(executable=executable, process=process)
    )

    handled = coordinator.handler(_task())

    assert handled.result_type == "research.search"
    assert handled.schema_version == "1.0"
    assert handled.result_document == {
        "schema_version": "1.0",
        "capability": "research.search",
        "query": "OpenAI",
        "limit": 5,
        "output": "search-output",
    }


def test_coordinator_recreation_after_worker_restart_keeps_gateway_contract(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "picotoopet-research-gateway"
    executable.write_text("fixture", encoding="utf-8")
    executable.chmod(0o755)
    process = RecordingProcess(
        GatewayProcessResult(
            returncode=0,
            stdout=json.dumps({"returncode": 0, "stdout": "search-output", "stderr": ""}),
            stderr="",
        )
    )

    # Worker restart 模拟：销毁第一套 coordinator/executor，再用同一固定 Gateway 入口创建新实例。
    first_worker = ResearchSearchCoordinator(
        ResearchGatewayExecutor(executable=executable, process=process)
    )
    first = first_worker.handler(_task("task-before-worker-restart"))
    del first_worker
    second_worker = ResearchSearchCoordinator(
        ResearchGatewayExecutor(executable=executable, process=process)
    )
    second = second_worker.handler(_task("task-after-worker-restart"))

    assert first.result_type == "research.search"
    assert second.result_type == "research.search"
    assert first.result_document == second.result_document
    assert len(process.calls) == 2
    assert all(call[0][1] == "--capability" for call in process.calls)
    assert all(call[0][2] == "research.search" for call in process.calls)


def test_executor_rejects_gateway_failure_without_exposing_stderr(tmp_path: Path) -> None:
    executable = tmp_path / "picotoopet-research-gateway"
    executable.write_text("fixture", encoding="utf-8")
    executable.chmod(0o755)
    process = RecordingProcess(
        GatewayProcessResult(returncode=7, stdout="", stderr="secret provider detail")
    )
    executor = ResearchGatewayExecutor(executable=executable, process=process)

    with pytest.raises(ResearchGatewayExecutionError, match="gateway process failed") as error:
        executor.search(query="OpenAI", limit=5, timeout_seconds=120)

    assert "secret provider detail" not in str(error.value)
