from picotoopet_core.mcp.registry import FROZEN_TOOL_NAMES, build_registry


EXPECTED = {
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
}


def test_registry_contains_exact_frozen_tool_contract() -> None:
    """MCP 工具名称不得擅自删除、改名或增加通用危险工具。"""

    registry = build_registry()

    assert set(FROZEN_TOOL_NAMES) == EXPECTED
    assert set(registry) == EXPECTED
    assert "shell" not in registry
    assert "read_file" not in registry
    assert "write_file" not in registry


def test_every_tool_has_closed_input_schema_and_permission_policy() -> None:
    """每个 MCP 工具都必须有封闭 Schema 和明确权限策略。"""

    registry = build_registry()

    for spec in registry.values():
        assert spec.input_schema["type"] == "object"
        assert spec.input_schema["additionalProperties"] is False
        assert "project_id" in spec.input_schema["properties"] or spec.name == "create_project"
        assert spec.permission_operation
        assert spec.timeout_seconds > 0
