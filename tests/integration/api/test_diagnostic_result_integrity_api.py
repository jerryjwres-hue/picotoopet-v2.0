"""已完成诊断任务的结果关联损坏必须返回稳定完整性错误。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.diagnostics.collector import collect_snapshot
from picotoopet_core.diagnostics.models import DiagnosticFacts, DiagnosticSnapshotRequest


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=token,
    )
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def complete_diagnostic(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    created_response = client.post(
        "/api/v1/tasks/system-diagnostic-snapshot",
        headers={**headers, "Idempotency-Key": "integrity-result"},
        json={"schema_version": "1.0", "sections": ["core"]},
    )
    assert created_response.status_code == 201
    created = created_response.json()
    services = client.app.state.services
    leased = services.queue.lease_next(
        "worker-m4",
        supported_task_types=("system.diagnostic_snapshot",),
    )
    assert leased is not None
    result = collect_snapshot(
        DiagnosticSnapshotRequest(sections=("core",)),
        DiagnosticFacts(
            core_version="2.3.0",
            core_health_state="online",
            database_schema_version=1,
            worker_id=None,
            worker_state="offline",
            worker_reason="not_requested",
            worker_supported_task_types=(),
            worker_last_heartbeat_at=None,
            queue_counts={},
            oldest_queued_age_seconds=None,
        ),
    )
    stored = services.results.put_json(
        result.model_dump(mode="json"),
        result_type="system.diagnostic_snapshot",
        max_bytes=64 * 1024,
    )
    completed = services.queue.complete_leased_with_result(
        created["task_id"],
        worker_id="worker-m4",
        stored_result=stored,
        schema_version="1.0",
    )
    assert completed.result_id is not None
    return {"task_id": created["task_id"], "result_id": completed.result_id}


def test_missing_result_metadata_is_integrity_error_not_not_found(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        completed = complete_diagnostic(client, headers)
        services = client.app.state.services
        services.database.execute(
            "DELETE FROM results WHERE result_id = ?",
            (completed["result_id"],),
        )
        response = client.get(
            f"/api/v1/tasks/{completed['task_id']}/result",
            headers=headers,
        )

    assert response.status_code == 500
    body = response.json()["error"]
    assert body["code"] == "RESULT_INTEGRITY_ERROR"
    assert body["retryable"] is False
    assert body["message"] == "诊断结果完整性校验失败。"


def test_result_metadata_for_wrong_task_is_integrity_error(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        completed = complete_diagnostic(client, headers)
        other = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"task_type": "analysis"},
        )
        assert other.status_code == 201
        other_task_id = other.json()["task_id"]
        services = client.app.state.services
        services.database.execute(
            "UPDATE results SET task_id = ? WHERE result_id = ?",
            (other_task_id, completed["result_id"]),
        )
        response = client.get(
            f"/api/v1/tasks/{completed['task_id']}/result",
            headers=headers,
        )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "RESULT_INTEGRITY_ERROR"


def test_result_store_io_failure_is_integrity_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, headers = make_client(tmp_path)
    with client:
        completed = complete_diagnostic(client, headers)
        services = client.app.state.services

        def fail_read(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise OSError("simulated storage failure")

        monkeypatch.setattr(services.results, "read_json", fail_read)
        response = client.get(
            f"/api/v1/tasks/{completed['task_id']}/result",
            headers=headers,
        )

    assert response.status_code == 500
    body = response.json()["error"]
    assert body["code"] == "RESULT_INTEGRITY_ERROR"
    assert body["retryable"] is False
    assert "storage" not in body["message"].lower()
