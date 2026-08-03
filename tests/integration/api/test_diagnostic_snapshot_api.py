"""Slice D 固定诊断创建、取消和结果 API 回归。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.diagnostics.collector import collect_snapshot
from picotoopet_core.diagnostics.models import (
    DiagnosticFacts,
    DiagnosticSnapshotRequest,
)


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=token,
    )
    client = TestClient(create_app(settings))
    return client, {"Authorization": f"Bearer {token}"}


def _request() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "sections": ["core", "worker", "queue"],
    }


def _result_document() -> dict[str, object]:
    result = collect_snapshot(
        DiagnosticSnapshotRequest(),
        DiagnosticFacts(
            core_version="2.3.0",
            core_health_state="online",
            database_schema_version=1,
            worker_id="worker-m4",
            worker_state="online",
            worker_reason="idle",
            worker_supported_task_types=(
                "system.noop",
                "system.diagnostic_snapshot",
            ),
            worker_last_heartbeat_at=datetime.now(UTC),
            queue_counts={"Queued": 1},
            oldest_queued_age_seconds=1,
        ),
    )
    return result.model_dump(mode="json")


def test_diagnostic_create_requires_auth_and_idempotency_key(
    tmp_path: Path,
) -> None:
    client, headers = make_client(tmp_path)
    with client:
        denied = client.post(
            "/api/v1/tasks/system-diagnostic-snapshot",
            json=_request(),
        )
        missing_key = client.post(
            "/api/v1/tasks/system-diagnostic-snapshot",
            headers=headers,
            json=_request(),
        )
        created = client.post(
            "/api/v1/tasks/system-diagnostic-snapshot",
            headers={**headers, "Idempotency-Key": "diagnostic-001"},
            json=_request(),
        )

    assert denied.status_code == 401
    assert missing_key.status_code == 422
    assert missing_key.json()["error"]["code"] == "VALIDATION_ERROR"
    assert created.status_code == 201
    body = created.json()
    assert body["task_type"] == "system.diagnostic_snapshot"
    assert body["priority"] == 50
    assert body["resource_tag"] == "system-diagnostic"
    assert body["max_attempts"] == 2
    assert body["timeout_seconds"] == 30
    assert body["status"] == "Queued"
    assert body["result_id"] is None


def test_generic_task_endpoint_rejects_reserved_diagnostic_type(
    tmp_path: Path,
) -> None:
    client, headers = make_client(tmp_path)
    with client:
        response = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={
                "task_type": "system.diagnostic_snapshot",
                "payload": {
                    "schema_version": "1.0",
                    "sections": ["core"],
                },
                "timeout_seconds": 3600,
            },
        )
        task_count = client.app.state.services.database.scalar(
            "SELECT COUNT(*) FROM tasks"
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "RESERVED_TASK_TYPE"
    assert task_count == 0


def test_diagnostic_create_is_idempotent_and_dedupes_active_task(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        first = client.post(
            "/api/v1/tasks/system-diagnostic-snapshot",
            headers={**headers, "Idempotency-Key": "diagnostic-001"},
            json=_request(),
        )
        repeated_transport = client.post(
            "/api/v1/tasks/system-diagnostic-snapshot",
            headers={**headers, "Idempotency-Key": "diagnostic-001"},
            json=_request(),
        )
        repeated_action = client.post(
            "/api/v1/tasks/system-diagnostic-snapshot",
            headers={**headers, "Idempotency-Key": "diagnostic-002"},
            json=_request(),
        )

    assert repeated_transport.json()["task_id"] == first.json()["task_id"]
    assert repeated_action.json()["task_id"] == first.json()["task_id"]


def test_diagnostic_create_rejects_unknown_duplicate_and_extra_fields(
    tmp_path: Path,
) -> None:
    client, headers = make_client(tmp_path)
    invalid_payloads = [
        {"schema_version": "1.0", "sections": ["logs"]},
        {"schema_version": "1.0", "sections": ["core", "core"]},
        {"schema_version": "1.0", "sections": ["core"], "task_type": "analysis"},
    ]

    with client:
        responses = [
            client.post(
                "/api/v1/tasks/system-diagnostic-snapshot",
                headers={**headers, "Idempotency-Key": f"invalid-{index}"},
                json=payload,
            )
            for index, payload in enumerate(invalid_payloads)
        ]

    assert [response.status_code for response in responses] == [422, 422, 422]
    assert all(
        response.json()["error"]["code"] == "VALIDATION_ERROR"
        for response in responses
    )


def test_running_cancel_records_intent_without_stealing_worker_terminal(
    tmp_path: Path,
) -> None:
    client, headers = make_client(tmp_path)
    with client:
        created = client.post(
            "/api/v1/tasks/system-diagnostic-snapshot",
            headers={**headers, "Idempotency-Key": "diagnostic-running"},
            json=_request(),
        ).json()
        services = client.app.state.services
        leased = services.queue.lease_next(
            "worker-m4",
            supported_task_types=("system.diagnostic_snapshot",),
        )
        assert leased is not None
        cancelled = client.post(
            f"/api/v1/tasks/{created['task_id']}/cancel",
            headers=headers,
        )
        pending = services.queue.is_cancel_requested(
            created["task_id"],
            worker_id="worker-m4",
        )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "Running"
    assert pending is True


def test_task_result_is_state_and_type_guarded_then_returns_strict_document(
    tmp_path: Path,
) -> None:
    client, headers = make_client(tmp_path)
    with client:
        created = client.post(
            "/api/v1/tasks/system-diagnostic-snapshot",
            headers={**headers, "Idempotency-Key": "diagnostic-result"},
            json=_request(),
        ).json()
        before = client.get(
            f"/api/v1/tasks/{created['task_id']}/result",
            headers=headers,
        )
        services = client.app.state.services
        services.queue.lease_next(
            "worker-m4",
            supported_task_types=("system.diagnostic_snapshot",),
        )
        stored = services.results.put_json(
            _result_document(),
            result_type="system.diagnostic_snapshot",
            max_bytes=64 * 1024,
        )
        completed = services.queue.complete_leased_with_result(
            created["task_id"],
            worker_id="worker-m4",
            stored_result=stored,
            schema_version="1.0",
        )
        response = client.get(
            f"/api/v1/tasks/{created['task_id']}/result",
            headers=headers,
        )

        other = client.post(
            "/api/v1/tasks",
            headers=headers,
            json={"task_type": "analysis"},
        ).json()
        wrong_type = client.get(
            f"/api/v1/tasks/{other['task_id']}/result",
            headers=headers,
        )

    assert before.status_code == 409
    assert completed.result_id is not None
    assert response.status_code == 200
    assert response.json()["schema_version"] == "1.0"
    assert len(response.content) <= 64 * 1024
    assert wrong_type.status_code == 404
