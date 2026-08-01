"""冻结 MCP 工具契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


FROZEN_TOOL_NAMES: tuple[str, ...] = (
    "create_project",
    "read_project",
    "read_analysis",
    "read_evidence",
    "list_assets",
    "submit_transcription",
    "submit_video_generation",
    "submit_video_edit",
    "submit_upscale",
    "submit_interpolation",
    "submit_ffmpeg_job",
    "create_report",
    "create_script",
    "create_shot_list",
    "create_comfyui_workflow",
    "create_handoff_package",
    "submit_coding_task",
    "write_result_back",
    "get_task_status",
    "cancel_task",
    "request_human_approval",
)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """单个 MCP 工具的固定契约。"""

    name: str
    description: str
    input_schema: dict[str, Any]
    permission_operation: str
    timeout_seconds: int


def _closed_schema(properties: dict[str, dict[str, Any]], required: list[str]) -> dict[str, Any]:
    """创建拒绝未知字段的 JSON Schema。"""

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _project_schema(*, payload: bool = False, task_id: bool = False) -> dict[str, Any]:
    """生成项目级 MCP 输入契约。"""

    properties: dict[str, dict[str, Any]] = {
        "project_id": {"type": "string", "minLength": 1},
        "trace_id": {"type": "string", "minLength": 1},
        "idempotency_key": {"type": "string", "minLength": 1},
    }
    required = ["project_id", "trace_id"]
    if payload:
        properties["payload"] = {"type": "object", "additionalProperties": True}
        required.append("payload")
    if task_id:
        properties["task_id"] = {"type": "string", "minLength": 1}
        required.append("task_id")
    return _closed_schema(properties, required)


def build_registry() -> dict[str, ToolSpec]:
    """返回精确冻结的工具清单，不包含通用 Shell 或任意文件工具。"""

    create_project = _closed_schema(
        {
            "title": {"type": "string", "minLength": 1},
            "project_type": {"type": "string", "minLength": 1},
            "source_app": {"type": "string", "minLength": 1},
            "classification": {"type": "string", "enum": ["PUBLIC", "INTERNAL", "PROTECTED"]},
            "trace_id": {"type": "string", "minLength": 1},
            "idempotency_key": {"type": "string", "minLength": 1},
        },
        ["title", "project_type", "source_app", "trace_id", "idempotency_key"],
    )
    definitions: dict[str, tuple[str, dict[str, Any], str, int]] = {
        "create_project": ("创建 V2 项目元数据。", create_project, "create", 30),
        "read_project": ("读取项目元数据。", _project_schema(), "read", 30),
        "read_analysis": ("读取项目分析结果。", _project_schema(), "read", 30),
        "read_evidence": ("受控读取项目证据。", _project_schema(), "read", 30),
        "list_assets": ("列出项目资产。", _project_schema(), "read", 30),
        "submit_transcription": ("提交 Windows 转录任务。", _project_schema(payload=True), "execute", 3600),
        "submit_video_generation": ("提交 Wan2.2 视频生成任务。", _project_schema(payload=True), "execute", 14400),
        "submit_video_edit": ("提交 Wan2.1 VACE 编辑任务。", _project_schema(payload=True), "execute", 14400),
        "submit_upscale": ("提交 Real-ESRGAN 放大任务。", _project_schema(payload=True), "execute", 7200),
        "submit_interpolation": ("提交 RIFE 补帧任务。", _project_schema(payload=True), "execute", 7200),
        "submit_ffmpeg_job": ("提交受限 FFmpeg 任务。", _project_schema(payload=True), "execute", 7200),
        "create_report": ("创建本地报告。", _project_schema(payload=True), "create", 1800),
        "create_script": ("创建内容脚本。", _project_schema(payload=True), "create", 1800),
        "create_shot_list": ("创建镜头表。", _project_schema(payload=True), "create", 1800),
        "create_comfyui_workflow": ("创建受控 ComfyUI 工作流。", _project_schema(payload=True), "create", 1800),
        "create_handoff_package": ("创建脱敏 Handoff 包。", _project_schema(payload=True), "create", 3600),
        "submit_coding_task": ("提交受限编码任务。", _project_schema(payload=True), "execute", 3600),
        "write_result_back": ("把结果写回 V2 Workspace。", _project_schema(payload=True), "update", 600),
        "get_task_status": ("读取任务状态。", _project_schema(task_id=True), "read", 30),
        "cancel_task": ("取消任务。", _project_schema(task_id=True), "update", 30),
        "request_human_approval": ("请求人工批准。", _project_schema(payload=True, task_id=True), "create", 30),
    }
    return {
        name: ToolSpec(
            name=name,
            description=definitions[name][0],
            input_schema=definitions[name][1],
            permission_operation=definitions[name][2],
            timeout_seconds=definitions[name][3],
        )
        for name in FROZEN_TOOL_NAMES
    }
