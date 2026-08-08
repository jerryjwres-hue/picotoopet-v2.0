"""Real workflow-to-worker regression for the platform diagnostic smoke flow."""

from __future__ import annotations

from pathlib import Path

from picotoopet_core.automation.models import (
    WorkflowCreate,
    WorkflowStatus,
    WorkflowStepCreate,
    WorkflowStepStatus,
)
from picotoopet_core.automation.service import WorkflowService
from picotoopet_core.db.database import Database
from picotoopet_core.diagnostics.collector import collect_snapshot
from picotoopet_core.diagnostics.models import DiagnosticFacts, DiagnosticSnapshotRequest
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.results.store import ResultStore
from picotoopet_core.worker.runtime import WorkerRuntime
from picotoopet_core.worker.state import WorkerStateStore


class SuccessfulDiagnosticRunner:
    """Deterministic in-process stand-in for the fixed diagnostic child process."""

    def run(
        self,
        request: DiagnosticSnapshotRequest,
        facts: DiagnosticFacts,
        *,
        output_dir: Path | str,
        timeout_seconds: float,
        cancel_requested,
    ) -> Path:  # type: ignore[no-untyped-def]
        assert timeout_seconds == 30
        assert cancel_requested() is False
        result = collect_snapshot(request, facts)
        output = Path(output_dir) / "diagnostic-result.json"
        output.write_text(result.model_dump_json(), encoding="utf-8")
        return output


def test_workflow_diagnostic_step_preserves_strict_payload_and_completes(
    tmp_path: Path,
) -> None:
    """Workflow metadata must never be injected into a strict task payload."""

    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    queue = DiagnosticQueueRepository(database)
    service = WorkflowService(database, queue=queue)
    payload = {
        "schema_version": "1.0",
        "sections": ["core", "worker", "queue"],
    }
    created = service.create_workflow(
        WorkflowCreate(
            project_id=None,
            name="platform-diagnostic-regression",
            priority=100,
            max_concurrency=1,
            idempotency_key="platform-diagnostic-regression-v1",
            steps=[
                WorkflowStepCreate(
                    step_key="diagnostic",
                    task_type="system.diagnostic_snapshot",
                    payload=payload,
                    max_attempts=2,
                    timeout_seconds=30,
                )
            ],
        )
    )

    running = service.reconcile(created.workflow_id)
    assert running.status is WorkflowStatus.RUNNING
    step = running.steps[0]
    assert step.status is WorkflowStepStatus.RUNNING
    assert step.task_id is not None

    queued = queue.get(step.task_id)
    assert queued.status is TaskStatus.QUEUED
    assert queued.payload == payload

    runtime = WorkerRuntime(
        queue=queue,
        state_store=WorkerStateStore(
            tmp_path / "state" / "worker-status.json",
            stale_after_seconds=30,
        ),
        worker_id="worker-regression",
        database=database,
        result_store=ResultStore(tmp_path / "results"),
        diagnostic_runner=SuccessfulDiagnosticRunner(),
        lease_seconds=60,
        heartbeat_seconds=5,
        poll_seconds=0.01,
    )
    cycle = runtime.run_once()
    assert cycle.processed is True
    assert cycle.succeeded is True
    assert queue.get(step.task_id).status is TaskStatus.COMPLETED

    completed = service.reconcile(created.workflow_id)
    assert completed.status is WorkflowStatus.COMPLETED
    assert completed.steps[0].status is WorkflowStepStatus.SUCCEEDED
    assert completed.steps[0].attempt_count == 1
    database.close()
