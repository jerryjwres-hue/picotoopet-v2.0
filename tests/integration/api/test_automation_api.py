from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=token,
    )
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def test_project_archive_is_metadata_only_and_platform_routes_are_authenticated(
    tmp_path: Path,
) -> None:
    client, headers = make_client(tmp_path)
    workspace = tmp_path / "user-project"
    workspace.mkdir()
    sentinel = workspace / "keep.txt"
    sentinel.write_text("do-not-touch", encoding="utf-8")

    with client:
        created = client.post(
            "/api/v1/projects",
            headers=headers,
            json={
                "title": "平台项目",
                "project_type": "automation",
                "source_app": "test",
                "classification": "INTERNAL",
                "workspace_root": str(workspace),
            },
        )
        assert created.status_code == 201
        project_id = created.json()["project_id"]

        archived = client.post(
            f"/api/v1/projects/{project_id}/archive",
            headers=headers,
        )
        assert archived.status_code == 200
        assert archived.json()["status"] == "Archived"
        assert sentinel.read_text(encoding="utf-8") == "do-not-touch"

        unauthenticated = client.get("/api/v1/workflows")
        assert unauthenticated.status_code == 401


def test_workflow_api_materializes_only_registered_queue_contract_and_health_is_real(
    tmp_path: Path,
) -> None:
    client, headers = make_client(tmp_path)
    with client:
        created = client.post(
            "/api/v1/workflows",
            headers=headers,
            json={
                "project_id": None,
                "name": "api-smoke",
                "priority": 25,
                "max_concurrency": 1,
                "idempotency_key": "api-smoke-v1",
                "steps": [
                    {
                        "step_key": "one",
                        "task_type": "system.noop",
                        "depends_on": [],
                        "required_capability": None,
                        "payload": {"purpose": "api-smoke"},
                        "max_attempts": 2,
                        "timeout_seconds": 30,
                    },
                    {
                        "step_key": "two",
                        "task_type": "system.noop",
                        "depends_on": ["one"],
                        "required_capability": None,
                        "payload": {},
                        "max_attempts": 2,
                        "timeout_seconds": 30,
                    },
                ],
            },
        )
        assert created.status_code == 201
        workflow_id = created.json()["workflow_id"]
        assert created.json()["status"] == "Ready"

        reconciled = client.post(
            f"/api/v1/workflows/{workflow_id}/reconcile",
            headers=headers,
        )
        assert reconciled.status_code == 200
        body = reconciled.json()
        assert body["status"] == "Running"
        first = next(step for step in body["steps"] if step["step_key"] == "one")
        second = next(step for step in body["steps"] if step["step_key"] == "two")
        assert first["status"] == "Running"
        assert first["task_id"]
        assert second["status"] == "Blocked"

        task = client.app.state.services.queue.get(first["task_id"])
        assert task.task_type == "system.noop"
        assert task.payload == {"purpose": "api-smoke"}

        health = client.get("/api/v1/automation/health", headers=headers)
        assert health.status_code == 200
        # Schema gate               Frugal escalation decisions extend Core schema to 21.
        assert health.json()["database_schema_version"] == 21
        assert health.json()["workflow_counts"]["Running"] == 1

        diagnostics = client.get("/api/v1/automation/diagnostics", headers=headers)
        assert diagnostics.status_code == 200
        assert diagnostics.json()["facts"] == []
