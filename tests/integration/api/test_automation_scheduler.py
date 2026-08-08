from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.domain.enums import TaskStatus


def _eventually(predicate, *, timeout_seconds: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition did not become true before timeout")


def test_core_scheduler_materializes_and_advances_workflow_without_manual_reconcile(
    tmp_path: Path,
) -> None:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=token,
        workflow_reconcile_seconds=0.05,
    )
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app(settings)) as client:
        created = client.post(
            "/api/v1/workflows",
            headers=headers,
            json={
                "project_id": None,
                "name": "automatic-two-step",
                "priority": 10,
                "max_concurrency": 1,
                "idempotency_key": "automatic-two-step-v1",
                "steps": [
                    {
                        "step_key": "one",
                        "task_type": "system.noop",
                        "depends_on": [],
                        "payload": {},
                        "max_attempts": 1,
                        "timeout_seconds": 30,
                    },
                    {
                        "step_key": "two",
                        "task_type": "system.noop",
                        "depends_on": ["one"],
                        "payload": {},
                        "max_attempts": 1,
                        "timeout_seconds": 30,
                    },
                ],
            },
        )
        assert created.status_code == 201
        workflow_id = created.json()["workflow_id"]
        services = client.app.state.services

        _eventually(lambda: services.database.scalar("SELECT COUNT(*) FROM tasks") == 1)
        workflow = services.workflows.get_workflow(workflow_id)
        first = next(step for step in workflow.steps if step.step_key == "one")
        assert first.task_id is not None

        services.queue.transition(first.task_id, TaskStatus.RUNNING, "scheduler-test-running")
        services.queue.transition(first.task_id, TaskStatus.COMPLETED, "scheduler-test-completed")

        _eventually(lambda: services.database.scalar("SELECT COUNT(*) FROM tasks") == 2)
        workflow = services.workflows.get_workflow(workflow_id)
        second = next(step for step in workflow.steps if step.step_key == "two")
        assert second.task_id is not None
        assert second.status.value == "Running"

        services.queue.transition(second.task_id, TaskStatus.RUNNING, "scheduler-test-running")
        services.queue.transition(second.task_id, TaskStatus.COMPLETED, "scheduler-test-completed")
        _eventually(
            lambda: services.workflows.get_workflow(workflow_id).status.value == "Completed"
        )
