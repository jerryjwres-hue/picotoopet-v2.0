"""MCP 工具到 Mac Core 服务的受控适配器。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from picotoopet_core.domain.enums import Classification, CloudPolicy, TaskStatus
from picotoopet_core.domain.models import ProjectCreate, TaskCreate
from picotoopet_core.permissions.gate import PermissionGate
from picotoopet_core.permissions.models import ActorType, Operation, PermissionRequest
from picotoopet_core.services import Services

from .registry import ToolSpec, build_registry


_TASK_TYPES = {
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
}


class McpToolExecutor:
    """验证工具、权限和参数后调用内部服务。"""

    def __init__(self, services: Services) -> None:
        self.services = services
        self.registry = build_registry()
        self.gate     = PermissionGate()

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """执行冻结工具；未知名称立即拒绝。"""

        spec = self.registry.get(tool_name)
        if spec is None:
            raise KeyError(f"未知 MCP 工具：{tool_name}")
        self._authorize(spec, arguments)

        if tool_name == "create_project":
            project = self.services.projects.create(
                ProjectCreate(
                    title=arguments["title"],
                    project_type=arguments["project_type"],
                    source_app=arguments["source_app"],
                    classification=Classification(arguments.get("classification", "INTERNAL")),
                )
            )
            return project.model_dump(mode="json")
        if tool_name == "read_project":
            return self.services.projects.get(arguments["project_id"]).model_dump(mode="json")
        if tool_name == "get_task_status":
            return self.services.queue.get(arguments["task_id"]).model_dump(mode="json")
        if tool_name == "cancel_task":
            task = self.services.queue.transition(
                arguments["task_id"],
                TaskStatus.CANCELLED,
                reason="mcp_cancel",
            )
            return task.model_dump(mode="json")
        if tool_name == "request_human_approval":
            payload = arguments["payload"]
            grant   = self.services.approvals.request(
                task_id=arguments["task_id"],
                approval_type=str(payload.get("approval_type", "manual")),
                scope=dict(payload.get("scope", {})),
                requested_by="mcp-tool",
                expires_at=datetime.now(UTC) + timedelta(seconds=int(payload.get("expires_seconds", 600))),
            )
            return grant.model_dump(mode="json")
        if tool_name in _TASK_TYPES:
            payload = dict(arguments.get("payload", {}))
            task = self.services.queue.create(
                TaskCreate(
                    project_id=arguments["project_id"],
                    task_type=tool_name,
                    payload=payload,
                    idempotency_key=arguments.get("idempotency_key"),
                    cloud_policy=(
                        CloudPolicy.CLOUD_MANUAL
                        if bool(payload.get("cloud_upload"))
                        else CloudPolicy.LOCAL_ONLY
                    ),
                )
            )
            return task.model_dump(mode="json")

        return {
            "status": "CAPABILITY_UNAVAILABLE",
            "tool": tool_name,
            "project_id": arguments["project_id"],
        }

    def _authorize(self, spec: ToolSpec, arguments: dict[str, Any]) -> None:
        """根据工具操作和项目分类调用默认拒绝权限门。"""

        classification = Classification.INTERNAL
        project_id      = arguments.get("project_id")
        if project_id:
            classification = self.services.projects.get(project_id).classification
        operation = Operation(spec.permission_operation)
        self.gate.authorize(
            PermissionRequest(
                actor_type=ActorType.MCP_TOOL,
                actor_id=spec.name,
                operation=operation,
                classification=classification,
                resource_id=str(project_id or spec.name),
            )
        )
