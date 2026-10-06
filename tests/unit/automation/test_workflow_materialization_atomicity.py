from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from picotoopet_core.automation.models import WorkflowCreate, WorkflowStepCreate
from picotoopet_core.automation.service import WorkflowService
from picotoopet_core.db.database import Database


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "workflow-materialization.db")
    database.open()
    database.apply_migrations()
    return database


def test_materialization_rolls_back_queue_task_when_step_binding_fails(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    service = WorkflowService(database)
    created = service.create_workflow(
        WorkflowCreate(
            project_id=None,
            name="atomic-materialization",
            priority=30,
            max_concurrency=1,
            idempotency_key="atomic-materialization-v1",
            steps=[
                WorkflowStepCreate(
                    step_key="one",
                    task_type="system.noop",
                )
            ],
        )
    )

    # Force the durable workflow-step link to fail after queue task creation.
    # The whole materialization must be one transaction so no orphan queue task becomes visible.
    database.execute(
        """
        CREATE TRIGGER fail_workflow_step_link
        BEFORE UPDATE OF task_id ON workflow_steps
        WHEN NEW.task_id IS NOT NULL
        BEGIN
            SELECT RAISE(ABORT, 'fixture_workflow_step_link_failure');
        END
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="fixture_workflow_step_link_failure"):
        service.reconcile(created.workflow_id)

    assert database.scalar("SELECT COUNT(*) FROM tasks") == 0
    step = service.get_workflow(created.workflow_id).steps[0]
    assert step.task_id is None
    assert step.attempt_count == 0
    database.close()
