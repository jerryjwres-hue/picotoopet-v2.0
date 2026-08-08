from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from picotoopet_core.automation.capabilities import CapabilityRouter
from picotoopet_core.automation.models import (
    CapabilityRegistration,
    QualityDecision,
    QualityOutcome,
    WorkflowCreate,
    WorkflowStatus,
    WorkflowStepCreate,
    WorkflowStepStatus,
)
from picotoopet_core.automation.quality import QualityGate
from picotoopet_core.automation.repository import AutomationRepository
from picotoopet_core.automation.service import WorkflowService
from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import TaskStatus


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "automation.db")
    database.open()
    database.apply_migrations()
    return database


def _workflow() -> WorkflowCreate:
    return WorkflowCreate(
        project_id=None,
        name="two-step",
        priority=30,
        max_concurrency=1,
        idempotency_key="two-step-v1",
        steps=[
            WorkflowStepCreate(step_key="one", task_type="system.noop"),
            WorkflowStepCreate(
                step_key="two",
                task_type="system.noop",
                depends_on=["one"],
            ),
        ],
    )


def _finish_task(service: WorkflowService, task_id: str, status: TaskStatus) -> None:
    service.queue.transition(task_id, TaskStatus.RUNNING, "test_running")
    service.queue.transition(task_id, status, f"test_{status.value.lower()}")


def test_workflow_create_is_idempotent_and_reconcile_materializes_queue_task(tmp_path: Path) -> None:
    database = _database(tmp_path)
    service = WorkflowService(database)

    first = service.create_workflow(_workflow())
    second = service.create_workflow(_workflow())
    assert second.workflow_id == first.workflow_id
    assert second.status is WorkflowStatus.READY

    running = service.reconcile(first.workflow_id)
    assert running.status is WorkflowStatus.RUNNING
    step_one = next(step for step in running.steps if step.step_key == "one")
    step_two = next(step for step in running.steps if step.step_key == "two")
    assert step_one.status is WorkflowStepStatus.RUNNING
    assert step_one.task_id is not None
    assert step_two.status is WorkflowStepStatus.BLOCKED
    task = service.queue.get(step_one.task_id)
    assert task.max_attempts == 1
    assert database.scalar("SELECT COUNT(*) FROM tasks") == 1
    database.close()


def test_dependency_unlock_pause_resume_cancel_and_restart_reconcile(tmp_path: Path) -> None:
    database = _database(tmp_path)
    service = WorkflowService(database)
    created = service.create_workflow(_workflow())
    running = service.reconcile(created.workflow_id)
    first = running.steps[0]
    assert first.task_id is not None
    _finish_task(service, first.task_id, TaskStatus.COMPLETED)

    paused = service.pause(created.workflow_id)
    assert paused.status is WorkflowStatus.PAUSED
    assert database.scalar("SELECT COUNT(*) FROM tasks") == 1
    database.close()

    reopened = _database(tmp_path)
    service = WorkflowService(reopened)
    resumed = service.resume(created.workflow_id)
    second = next(step for step in resumed.steps if step.step_key == "two")
    assert second.status is WorkflowStepStatus.RUNNING
    assert second.task_id is not None
    assert reopened.scalar("SELECT COUNT(*) FROM tasks") == 2

    cancelled = service.cancel(created.workflow_id)
    assert cancelled.status is WorkflowStatus.CANCELLED
    current_task = service.queue.get(second.task_id)
    assert current_task.status is TaskStatus.CANCELLED
    reopened.close()


def test_workflow_retry_budget_is_not_multiplied_by_queue_retry_budget(tmp_path: Path) -> None:
    database = _database(tmp_path)
    service = WorkflowService(database)
    created = service.create_workflow(
        WorkflowCreate(
            project_id=None,
            name="bounded-retry",
            priority=50,
            max_concurrency=1,
            idempotency_key="bounded-retry-v1",
            steps=[
                WorkflowStepCreate(
                    step_key="fragile",
                    task_type="system.noop",
                    max_attempts=2,
                    timeout_seconds=30,
                )
            ],
        )
    )

    first = service.reconcile(created.workflow_id).steps[0]
    assert first.task_id is not None
    assert service.queue.get(first.task_id).max_attempts == 1
    _finish_task(service, first.task_id, TaskStatus.FAILED)

    second = service.reconcile(created.workflow_id).steps[0]
    assert second.status is WorkflowStepStatus.RUNNING
    assert second.attempt_count == 2
    assert second.task_id is not None
    assert second.task_id != first.task_id
    assert service.queue.get(second.task_id).max_attempts == 1
    _finish_task(service, second.task_id, TaskStatus.FAILED)

    terminal = service.reconcile(created.workflow_id)
    assert terminal.status is WorkflowStatus.FAILED
    assert terminal.steps[0].status is WorkflowStepStatus.FAILED
    assert terminal.steps[0].attempt_count == 2
    assert database.scalar("SELECT COUNT(*) FROM tasks") == 2
    database.close()


def test_capability_router_rejects_stale_and_tie_breaks_worker_id(tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository = AutomationRepository(database)
    router = CapabilityRouter(repository, stale_after=timedelta(minutes=2))
    now = datetime.now(UTC)
    router.register(
        CapabilityRegistration(
            worker_id="worker-b",
            capability="local.text.analysis",
            task_types=["analysis.safe"],
            heartbeat_at=now,
        )
    )
    router.register(
        CapabilityRegistration(
            worker_id="worker-a",
            capability="local.text.analysis",
            task_types=["analysis.safe"],
            heartbeat_at=now,
        )
    )
    router.register(
        CapabilityRegistration(
            worker_id="worker-stale",
            capability="local.text.analysis",
            task_types=["analysis.safe"],
            heartbeat_at=now - timedelta(minutes=10),
        )
    )

    selected = router.select(
        "local.text.analysis",
        task_type="analysis.safe",
        now=now,
    )
    assert selected is not None
    assert selected.worker_id == "worker-a"
    assert router.select("local.text.analysis", task_type="unknown", now=now) is None
    database.close()


def test_quality_decision_is_persisted_and_moves_step_to_attention_state(tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository = AutomationRepository(database)
    service = WorkflowService(database, repository=repository)
    created = service.create_workflow(_workflow())
    gate = QualityGate(repository)

    record = gate.decide(
        QualityDecision(
            workflow_id=created.workflow_id,
            step_key="one",
            outcome=QualityOutcome.NEEDS_HUMAN,
            rule_id="manual-check",
            evidence={"reason": "fixture"},
        )
    )
    assert record.outcome is QualityOutcome.NEEDS_HUMAN
    updated = service.reconcile(created.workflow_id)
    assert updated.status is WorkflowStatus.NEEDS_ATTENTION
    assert updated.steps[0].status is WorkflowStepStatus.NEEDS_HUMAN
    assert database.scalar("SELECT COUNT(*) FROM quality_decisions") == 1
    database.close()


def test_quality_pass_completes_step_and_unlocks_dependency(tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository = AutomationRepository(database)
    service = WorkflowService(database, repository=repository)
    created = service.create_workflow(_workflow())
    gate = QualityGate(repository)

    gate.decide(
        QualityDecision(
            workflow_id=created.workflow_id,
            step_key="one",
            outcome=QualityOutcome.PASS,
            rule_id="quality-pass",
            evidence={"score": 0.99},
        )
    )
    updated = service.reconcile(created.workflow_id)
    first = next(step for step in updated.steps if step.step_key == "one")
    second = next(step for step in updated.steps if step.step_key == "two")
    assert first.status is WorkflowStepStatus.SUCCEEDED
    assert second.status is WorkflowStepStatus.RUNNING
    database.close()


def test_quality_retry_cannot_exceed_step_attempt_budget(tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository = AutomationRepository(database)
    service = WorkflowService(database, repository=repository)
    gate = QualityGate(repository)
    created = service.create_workflow(
        WorkflowCreate(
            project_id=None,
            name="quality-retry-budget",
            priority=50,
            max_concurrency=1,
            idempotency_key="quality-retry-budget-v1",
            steps=[
                WorkflowStepCreate(
                    step_key="quality",
                    task_type="system.noop",
                    max_attempts=1,
                    timeout_seconds=30,
                )
            ],
        )
    )
    running = service.reconcile(created.workflow_id)
    assert running.steps[0].attempt_count == 1

    gate.decide(
        QualityDecision(
            workflow_id=created.workflow_id,
            step_key="quality",
            outcome=QualityOutcome.RETRY,
            rule_id="quality-retry",
            evidence={"score": 0.2},
        )
    )
    terminal = service.reconcile(created.workflow_id)
    assert terminal.status is WorkflowStatus.FAILED
    assert terminal.steps[0].status is WorkflowStepStatus.FAILED
    assert terminal.steps[0].failure_code == "QUALITY_RETRY_EXHAUSTED"
    assert terminal.steps[0].attempt_count == 1
    assert database.scalar("SELECT COUNT(*) FROM tasks") == 1
    database.close()
