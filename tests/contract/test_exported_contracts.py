import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "contracts" / "schemas"


def test_exported_json_schemas_are_valid_and_complete() -> None:
    """冻结数据契约必须全部存在并通过 JSON Schema 自校验。"""

    required = {
        "project_v2.schema.json",
        "artifact_v2.schema.json",
        "task_v2.schema.json",
        "result_v2.schema.json",
        "approval_v2.schema.json",
        "connector_event_v2.schema.json",
    }
    assert required <= {path.name for path in SCHEMAS.glob("*.json")}
    for name in required:
        schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema.get("additionalProperties") is False


def test_openapi_and_mcp_contracts_match_phase_one_surface() -> None:
    """OpenAPI 和 MCP 导出必须包含冻结的主要接口与工具。"""

    openapi = json.loads(
        (ROOT / "contracts" / "openapi" / "mac_core_v1.openapi.json").read_text(
            encoding="utf-8"
        )
    )
    tools = json.loads(
        (ROOT / "contracts" / "mcp" / "tools_v1.json").read_text(encoding="utf-8")
    )

    assert openapi["openapi"].startswith("3.")
    assert "/api/v1/health" in openapi["paths"]
    assert "/api/v1/tasks" in openapi["paths"]
    assert "/api/v1/events" in openapi["paths"]
    assert len(tools["tools"]) == 21
    assert {tool["name"] for tool in tools["tools"]} >= {
        "submit_video_generation",
        "submit_video_edit",
        "request_human_approval",
    }


def test_contract_exports_do_not_contain_runtime_secret() -> None:
    """导出契约不得包含生成 OpenAPI 时使用的测试令牌。"""

    secret = "contract-export-token-0123456789"
    content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "contracts").rglob("*.json")
    )
    assert secret not in content
