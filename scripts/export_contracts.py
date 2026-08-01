"""导出冻结 JSON Schema、OpenAPI 和 MCP 工具契约。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.domain.contracts import (
    ApprovalContract,
    ArtifactContract,
    ConnectorEventContract,
    ProjectContract,
    ResultContract,
    TaskContract,
)
from picotoopet_core.mcp.registry import build_registry


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, payload: object) -> None:
    """以稳定顺序写入 UTF-8 JSON。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def export_schemas() -> None:
    """导出六个冻结数据模型。"""

    models = {
        "project_v2.schema.json": ProjectContract,
        "artifact_v2.schema.json": ArtifactContract,
        "task_v2.schema.json": TaskContract,
        "result_v2.schema.json": ResultContract,
        "approval_v2.schema.json": ApprovalContract,
        "connector_event_v2.schema.json": ConnectorEventContract,
    }
    for filename, model in models.items():
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        _write_json(ROOT / "contracts" / "schemas" / filename, schema)


def export_openapi() -> None:
    """导出 REST OpenAPI，并显式登记 WebSocket 扩展。"""

    with tempfile.TemporaryDirectory(prefix="picotoopet-contract-") as temporary:
        settings = AppSettings(
            paths=RuntimePaths.from_root(Path(temporary) / "runtime"),
            api_token="contract-export-token-0123456789",
        )
        app = create_app(settings)
        try:
            schema = app.openapi()
            schema.setdefault("paths", {})["/api/v1/events"] = {
                "x-websocket": True,
                "summary": "认证后的任务与健康事件流",
            }
            _write_json(
                ROOT / "contracts" / "openapi" / "mac_core_v1.openapi.json",
                schema,
            )
        finally:
            app.state.services.close()


def export_mcp() -> None:
    """导出工具和标准错误码。"""

    registry = build_registry()
    tools = {
        "schema_version": "2.2.0",
        "tools": [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema,
                "permission_operation": spec.permission_operation,
                "timeout_seconds": spec.timeout_seconds,
            }
            for spec in registry.values()
        ],
    }
    errors = {
        "schema_version": "2.2.0",
        "errors": [
            "VALIDATION_ERROR",
            "AUTHENTICATION_REQUIRED",
            "PERMISSION_DENIED",
            "APPROVAL_REQUIRED",
            "NOT_FOUND",
            "CONFLICT",
            "CAPABILITY_UNAVAILABLE",
            "TIMEOUT",
            "RETRY_EXHAUSTED",
            "RESULT_INTEGRITY_ERROR",
            "SERVICE_UNAVAILABLE",
            "INTERNAL_ERROR",
        ],
    }
    _write_json(ROOT / "contracts" / "mcp" / "tools_v1.json", tools)
    _write_json(ROOT / "contracts" / "mcp" / "errors_v1.json", errors)


def main() -> None:
    """执行全部导出。"""

    export_schemas()
    export_openapi()
    export_mcp()


if __name__ == "__main__":
    main()
