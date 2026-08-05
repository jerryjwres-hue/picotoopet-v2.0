"""Slice D 固定诊断任务 OpenAPI 合同回归。"""

from __future__ import annotations

from pathlib import Path

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def _openapi(tmp_path: Path) -> dict[str, object]:
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token="0123456789abcdef0123456789abcdef",
    )
    return create_app(settings).openapi()


def test_diagnostic_create_is_fixed_and_does_not_accept_task_type(tmp_path: Path) -> None:
    document = _openapi(tmp_path)
    paths = document["paths"]
    operation = paths["/api/v1/tasks/system-diagnostic-snapshot"]["post"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]

    assert request_schema == {
        "$ref": "#/components/schemas/DiagnosticSnapshotRequest"
    }
    schema = document["components"]["schemas"]["DiagnosticSnapshotRequest"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"schema_version", "sections"}
    assert "task_type" not in schema["properties"]
    assert schema["properties"]["schema_version"]["const"] == "1.0"


def test_task_result_contract_is_fixed_and_task_record_exposes_result_id(
    tmp_path: Path,
) -> None:
    document = _openapi(tmp_path)
    paths = document["paths"]
    result_operation = paths["/api/v1/tasks/{task_id}/result"]["get"]
    response_schema = result_operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"]

    assert response_schema == {
        "$ref": "#/components/schemas/DiagnosticSnapshotResult"
    }
    result_schema = document["components"]["schemas"]["DiagnosticSnapshotResult"]
    assert result_schema["additionalProperties"] is False
    assert set(result_schema["properties"]) == {
        "schema_version",
        "generated_at",
        "core",
        "worker",
        "queue",
        "checks",
        "warnings",
    }
    task_schema = document["components"]["schemas"]["TaskRecord"]
    assert "result_id" in task_schema["properties"]


def test_existing_generic_task_api_remains_available(tmp_path: Path) -> None:
    document = _openapi(tmp_path)

    assert "/api/v1/tasks" in document["paths"]
    assert "post" in document["paths"]["/api/v1/tasks"]
    assert "/api/v1/tasks/{task_id}/cancel" in document["paths"]
    assert "/api/v1/tasks/{task_id}/retry" in document["paths"]
