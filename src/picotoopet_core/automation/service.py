"""Durable workflow orchestration above the existing queue."""

from __future__ import annotations

from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.queue.repository import QueueRepository

from .capabilities import CapabilityRouter
from .models import (
    WorkflowCreate,
    WorkflowRecord,
    WorkflowStatus,
    WorkflowStepRecord,
    WorkflowStepStatus,
)
from .repository import AutomationRepository

_ACTIVE_TASK_STATUSES = {
    TaskStatus.CREATED,
    TaskStatus.VALIDATING,
    TaskStatus.QUEUED,
    TaskStatus.RUNNING,
    TaskStatus.WAITING_FOR_TOOL,
    TaskStatus.WAITING_FOR_APPROVAL,
    TaskStatus.RETRYING,
}
_TERMINAL_WORKFLOW_STATUSES = {
    WorkflowStatus.COMPLETED,
    WorkflowStatus.CANCELLED,
    WorkflowStatus.FAILED,
}


class WorkflowService:
    """Reconcile durable workflow facts into normal queue tasks."""

    def __init__(
        self,
        database: Database,
        queue: QueueRepository | None = None,
        repository: AutomationRepository | None = None,
    ) -> None:
        self.database = database
        self.queue = queue or QueueRepository(database)
        self.repository = repository or AutomationRepository(database)
        self.capabilities = CapabilityRouter(self.repository)

    def create_workflow(self, request: WorkflowCreate) -> WorkflowRecord:
        """Create metadata only; explicit reconcile starts materialization."""

        return self.repository.create_workflow(request)

    def get_workflow(self, workflow_id: str) -> WorkflowRecord:
        return self.repository.get_workflow(workflow_id)

    def list_workflows(self, *, limit: int = 200) -> list[WorkflowRecord]:
        return self.repository.list_workflows(limit=limit)

    def reconcile(self, workflow_id: str) -> WorkflowRecord:
        """Replay-safe state reconciliation; never executes a task inline."""

        workflow = self.repository.get_workflow(workflow_id)
        if workflow.status in _TERMINAL_WORKFLOW_STATUSES or workflow.status is WorkflowStatus.PAUSED:
            return workflow

        self._refresh_materialized_steps(workflow)
        workflow = self.repository.get_workflow(workflow_id)
        self._unlock_dependencies(workflow)
        workflow = self.repository.get_workflow(workflow_id)

        attention = any(
            step.status
            in {
                WorkflowStepStatus.NEEDS_HUMAN,
                WorkflowStepStatus.NEEDS_DEEP_AI,
            }
            for step in workflow.steps
        )
        if attention:
            self.repository.update_workflow_status(
                workflow_id,
                WorkflowStatus.NEEDS_ATTENTION,
            )
            self._checkpoint(workflow_id, "workflow.needs_attention")
            return self.repository.get_workflow(workflow_id)

        if any(step.status in {WorkflowStepStatus.FAILED, WorkflowStepStatus.REJECTED} for step in workflow.steps):
            self.repository.update_workflow_status(
                workflow_id,
                WorkflowStatus.FAILED,
                failure_code="WORKFLOW_STEP_FAILED",
                finished=True,
            )
            self._checkpoint(workflow_id, "workflow.failed")
            return self.repository.get_workflow(workflow_id)

        if all(step.status is WorkflowStepStatus.SUCCEEDED for step in workflow.steps):
            self.repository.update_workflow_status(
                workflow_id,
                WorkflowStatus.COMPLETED,
                finished=True,
            )
            self._checkpoint(workflow_id, "workflow.completed")
            return self.repository.get_workflow(workflow_id)

        active = sum(
            1 for step in workflow.steps if step.status is WorkflowStepStatus.RUNNING
        )
        capacity = max(0, workflow.max_concurrency - active)
        if capacity:
            for step in workflow.steps:
                if capacity <= 0:
                    break
                if step.status not in {
                    WorkflowStepStatus.READY,
                    WorkflowStepStatus.RETRY_WAITING,
                }:
                    continue
                if step.required_capability is not None:
                    route = self.capabilities.select(
                        step.required_capability,
                        task_type=step.task_type,
                    )
                    if route is None:
                        continue
                self._materialize(workflow, step)
                capacity -= 1

        workflow = self.repository.get_workflow(workflow_id)
        if any(
            step.status is WorkflowStepStatus.RUNNING
            for step in workflow.steps
        ):
            self.repository.update_workflow_status(workflow_id, WorkflowStatus.RUNNING)
        elif workflow.status is WorkflowStatus.NEEDS_ATTENTION:
            self.repository.update_workflow_status(workflow_id, WorkflowStatus.READY)
        self._checkpoint(workflow_id, "workflow.reconciled")
        return self.repository.get_workflow(workflow_id)

    def pause(self, workflow_id: str) -> WorkflowRecord:
        workflow = self.repository.get_workflow(workflow_id)
        if workflow.status in _TERMINAL_WORKFLOW_STATUSES:
            return workflow
        self.repository.update_workflow_status(workflow_id, WorkflowStatus.PAUSED)
        self._checkpoint(workflow_id, "workflow.paused")
        return self.repository.get_workflow(workflow_id)

    def resume(self, workflow_id: str) -> WorkflowRecord:
        workflow = self.repository.get_workflow(workflow_id)
        if workflow.status in _TERMINAL_WORKFLOW_STATUSES:
            return workflow
        self.repository.update_workflow_status(workflow_id, WorkflowStatus.READY)
        self._checkpoint(workflow_id, "workflow.resumed")
        return self.reconcile(workflow_id)

    def cancel(self, workflow_id: str) -> WorkflowRecord:
        workflow = self.repository.get_workflow(workflow_id)
        if workflow.status in _TERMINAL_WORKFLOW_STATUSES:
            return workflow
        for step in workflow.steps:
            if step.status in {
                WorkflowStepStatus.SUCCEEDED,
                WorkflowStepStatus.FAILED,
                WorkflowStepStatus.REJECTED,
                WorkflowStepStatus.CANCELLED,
            }:
                continue
            if step.task_id is not None:
                task = self.queue.get(step.task_id)
                if task.status in _ACTIVE_TASK_STATUSES:
                    self.queue.transition(
                        step.task_id,
                        TaskStatus.CANCELLED,
                        "workflow_cancelled",
                    )
            self.repository.update_step(
                workflow_id,
                step.step_key,
                status=WorkflowStepStatus.CANCELLED,
                finished=True,
            )
        self.repository.update_workflow_status(
            workflow_id,
            WorkflowStatus.CANCELLED,
            finished=True,
        )
        self._checkpoint(workflow_id, "workflow.cancelled")
        return self.repository.get_workflow(workflow_id)

    def _refresh_materialized_steps(self, workflow: WorkflowRecord) -> None:
        for step in workflow.steps:
            if step.task_id is None or step.status is not WorkflowStepStatus.RUNNING:
                continue
            task = self.queue.get(step.task_id)
            if task.status is TaskStatus.COMPLETED:
                self.repository.update_step(
                    workflow.workflow_id,
                    step.step_key,
                    status=WorkflowStepStatus.SUCCEEDED,
                    finished=True,
                )
            elif task.status is TaskStatus.FAILED:
                target = (
                    WorkflowStepStatus.RETRY_WAITING
                    if step.attempt_count < step.max_attempts
                    else WorkflowStepStatus.FAILED
                )
                self.repository.update_step(
                    workflow.workflow_id,
                    step.step_key,
                    status=target,
                    failure_code=task.error_code,
                    error_message=task.error_message,
                    finished=target is WorkflowStepStatus.FAILED,
                )
            elif task.status is TaskStatus.CANCELLED:
                self.repository.update_step(
                    workflow.workflow_id,
                    step.step_key,
                    status=WorkflowStepStatus.CANCELLED,
                    finished=True,
                )

    def _unlock_dependencies(self, workflow: WorkflowRecord) -> None:
        status_by_key = {step.step_key: step.status for step in workflow.steps}
        for step in workflow.steps:
            if step.status not in {
                WorkflowStepStatus.BLOCKED,
                WorkflowStepStatus.PENDING,
            }:
                continue
            if all(
                status_by_key[dependency] is WorkflowStepStatus.SUCCEEDED
                for dependency in step.depends_on
            ):
                self.repository.update_step(
                    workflow.workflow_id,
                    step.step_key,
                    status=WorkflowStepStatus.READY,
                )

    def _materialize(self, workflow: WorkflowRecord, step: WorkflowStepRecord) -> None:
        next_attempt = step.attempt_count + 1
        request = TaskCreate(
            project_id=workflow.project_id,
            task_type=step.task_type,
            # Task payload belongs exclusively to the task contract. Workflow linkage
            # stays in durable workflow-step facts, resource_tag and idempotency_key.
            payload=step.payload,
            priority=workflow.priority,
            resource_tag=f"workflow:{workflow.workflow_id}",
            idempotency_key=(
                f"workflow:{workflow.workflow_id}:step:{step.step_key}:attempt:{next_attempt}"
            ),
            # Workflow owns the bounded retry budget; each queue task is one physical attempt.
            max_attempts=1,
            timeout_seconds=step.timeout_seconds,
        )

        # Queue task creation (including task event/outbox facts) and workflow-step binding
        # are one durability unit. Database.execute() reuses this same SQLite connection,
        # so a binding failure rolls the task back instead of leaving an orphan task visible.
        with self.database.transaction() as connection:
            task = self.queue._create_in_transaction(connection, request=request)
            self.repository.update_step(
                workflow.workflow_id,
                step.step_key,
                status=WorkflowStepStatus.RUNNING,
                task_id=task.task_id,
                increment_attempt=True,
            )

    def _checkpoint(self, workflow_id: str, event: str) -> None:
        workflow = self.repository.get_workflow(workflow_id)
        self.repository.record_checkpoint(
            workflow_id,
            step_key=None,
            state={
                "event": event,
                "status": workflow.status.value,
                "steps": {
                    step.step_key: {
                        "status": step.status.value,
                        "attempt_count": step.attempt_count,
                        "task_id": step.task_id,
                    }
                    for step in workflow.steps
                },
            },
        )
