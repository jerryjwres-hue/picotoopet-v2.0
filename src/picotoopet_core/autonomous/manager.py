"""Thin autonomous scheduler that feeds the existing durable WorkflowService."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from picotoopet_core.automation.models import (
    WorkflowCreate,
    WorkflowStatus,
    WorkflowStepCreate,
)
from picotoopet_core.automation.service import WorkflowService
from picotoopet_core.db.database import Database
from picotoopet_core.domain.enums import TaskStatus

from .models import GoalCreate, GoalOrigin, GoalRecord, GoalStatus, PriorityClass
from .repository import AutonomousGoalRepository

# P3 autonomous discovery requires a real search/crawler-backed capability.
# A healthy local language model alone is only an analysis worker and cannot
# manufacture discovery evidence or trends from an empty context.
_DISCOVERY_CAPABILITY = "content.discovery"
_DISCOVERY_TASK_TYPE = "autonomous.discovery.v1"
_ACTIVE_TASK_STATUSES = (
    TaskStatus.CREATED,
    TaskStatus.VALIDATING,
    TaskStatus.QUEUED,
    TaskStatus.RUNNING,
    TaskStatus.WAITING_FOR_TOOL,
    TaskStatus.WAITING_FOR_APPROVAL,
    TaskStatus.RETRYING,
)
_ACTIVE_WORKFLOW_STATUSES = (
    WorkflowStatus.READY,
    WorkflowStatus.RUNNING,
    WorkflowStatus.NEEDS_ATTENTION,
)
_TERMINAL_WORKFLOW_TO_GOAL = {
    WorkflowStatus.COMPLETED: GoalStatus.COMPLETED,
    WorkflowStatus.CANCELLED: GoalStatus.CANCELLED,
    WorkflowStatus.FAILED: GoalStatus.FAILED,
}


@dataclass(frozen=True, slots=True)
class AutonomousTickResult:
    """Small observable result for health/UI telemetry; execution remains elsewhere."""

    action: str
    created_goal_id: str | None = None
    active_goal_id: str | None = None
    workflow_id: str | None = None


class AutonomousOperationsManager:
    """Create low-priority work only when existing explicit work is not active."""

    def __init__(
        self,
        *,
        database: Database,
        goals: AutonomousGoalRepository,
        workflows: WorkflowService,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database = database
        self.goals = goals
        self.workflows = workflows
        self._clock = clock or (lambda: datetime.now(UTC))

    def tick(self) -> AutonomousTickResult:
        """Perform one replay-safe scheduling decision; never execute a provider inline."""

        now = self._now()
        self._repair_interrupted_bindings()

        active = self._find_active_autonomous_goal()
        if active is not None:
            return self._reconcile_active(active)

        if self._has_explicit_active_work():
            return AutonomousTickResult(action="yield_explicit_work")

        discovery = self.workflows.capabilities.select(
            _DISCOVERY_CAPABILITY,
            task_type=_DISCOVERY_TASK_TYPE,
            now=now,
        )
        if discovery is not None:
            return self._create_discovery(now)
        return self._create_maintenance(now)

    def _create_discovery(self, now: datetime) -> AutonomousTickResult:
        bucket = now.strftime("%Y-%m-%dT%H")
        key = f"autonomous:content-discovery:{bucket}"
        objective = "发现近期高增长、可进一步研究的内容主题候选"
        goal = self.goals.create(
            GoalCreate(
                origin=GoalOrigin.AUTONOMOUS,
                intent_type="content.discover",
                priority_class=PriorityClass.P3,
                objective=objective,
                constraints={"read_only": True, "bounded_round": True},
                budget_class="tool-first-local-analysis",
                idempotency_key=key,
            )
        )
        workflow = self.workflows.create_workflow(
            WorkflowCreate(
                name="PicotooPet AI autonomous content discovery",
                priority=PriorityClass.P3.queue_priority,
                max_concurrency=1,
                idempotency_key=key,
                steps=[
                    WorkflowStepCreate(
                        step_key="content-discovery",
                        task_type=_DISCOVERY_TASK_TYPE,
                        required_capability=_DISCOVERY_CAPABILITY,
                        payload={
                            "objective": objective,
                            "read_only": True,
                            "max_candidates": 50,
                        },
                        max_attempts=2,
                        timeout_seconds=900,
                    )
                ],
            )
        )
        goal = self.goals.bind_workflow(goal.goal_id, workflow.workflow_id)
        workflow = self.workflows.reconcile(workflow.workflow_id)
        self._sync_goal_status(goal, workflow.status)
        return AutonomousTickResult(
            action="created_discovery",
            created_goal_id=goal.goal_id,
            active_goal_id=goal.goal_id,
            workflow_id=workflow.workflow_id,
        )

    def _create_maintenance(self, now: datetime) -> AutonomousTickResult:
        bucket = now.strftime("%Y-%m-%d")
        key = f"autonomous:maintenance-health:{bucket}"
        goal = self.goals.create(
            GoalCreate(
                origin=GoalOrigin.SYSTEM,
                intent_type="system.maintenance_health",
                priority_class=PriorityClass.P4,
                objective="执行低优先级 Mac Core/Worker/Queue 健康检查",
                constraints={"read_only": True},
                budget_class="deterministic",
                idempotency_key=key,
            )
        )
        workflow = self.workflows.create_workflow(
            WorkflowCreate(
                name="PicotooPet AI background health maintenance",
                priority=PriorityClass.P4.queue_priority,
                max_concurrency=1,
                idempotency_key=key,
                steps=[
                    WorkflowStepCreate(
                        step_key="diagnostic-snapshot",
                        task_type="system.diagnostic_snapshot",
                        payload={},
                        max_attempts=2,
                        timeout_seconds=120,
                    )
                ],
            )
        )
        goal = self.goals.bind_workflow(goal.goal_id, workflow.workflow_id)
        workflow = self.workflows.reconcile(workflow.workflow_id)
        self._sync_goal_status(goal, workflow.status)
        return AutonomousTickResult(
            action="created_maintenance",
            created_goal_id=goal.goal_id,
            active_goal_id=goal.goal_id,
            workflow_id=workflow.workflow_id,
        )

    def _find_active_autonomous_goal(self) -> GoalRecord | None:
        for goal in self.goals.list(limit=500):
            if goal.priority_class not in {PriorityClass.P3, PriorityClass.P4}:
                continue
            if goal.workflow_id is None:
                continue
            workflow = self.workflows.get_workflow(goal.workflow_id)
            terminal = _TERMINAL_WORKFLOW_TO_GOAL.get(workflow.status)
            if terminal is not None:
                if goal.status is not terminal:
                    self.goals.update_status(goal.goal_id, terminal)
                continue
            if workflow.status is WorkflowStatus.PAUSED:
                continue
            return goal
        return None

    def _reconcile_active(self, goal: GoalRecord) -> AutonomousTickResult:
        assert goal.workflow_id is not None
        workflow = self.workflows.reconcile(goal.workflow_id)
        self._sync_goal_status(goal, workflow.status)
        return AutonomousTickResult(
            action="reconciled_autonomous",
            active_goal_id=goal.goal_id,
            workflow_id=workflow.workflow_id,
        )

    def _repair_interrupted_bindings(self) -> None:
        """Repair a crash between idempotent workflow creation and Goal binding."""

        for goal in self.goals.list(limit=500):
            if goal.priority_class not in {PriorityClass.P3, PriorityClass.P4}:
                continue
            if goal.workflow_id is not None:
                continue
            row = self.database.fetchone(
                "SELECT workflow_id FROM workflow_runs WHERE idempotency_key = ?",
                (goal.idempotency_key,),
            )
            if row is not None:
                self.goals.bind_workflow(goal.goal_id, row["workflow_id"])

    def _has_explicit_active_work(self) -> bool:
        """Treat anything not bound to a P3/P4 Goal as explicit work and yield to it."""

        task_placeholders = ",".join("?" for _ in _ACTIVE_TASK_STATUSES)
        task_count = self.database.scalar(
            f"""
            SELECT COUNT(*)
            FROM tasks AS task
            WHERE task.status IN ({task_placeholders})
              AND NOT EXISTS (
                  SELECT 1
                  FROM autonomous_goals AS goal
                  WHERE goal.workflow_id IS NOT NULL
                    AND goal.priority_class IN (?, ?)
                    AND task.resource_tag = ('workflow:' || goal.workflow_id)
              )
            """,
            (
                *(status.value for status in _ACTIVE_TASK_STATUSES),
                PriorityClass.P3.value,
                PriorityClass.P4.value,
            ),
        )
        if int(task_count or 0) > 0:
            return True

        workflow_placeholders = ",".join("?" for _ in _ACTIVE_WORKFLOW_STATUSES)
        workflow_count = self.database.scalar(
            f"""
            SELECT COUNT(*)
            FROM workflow_runs AS workflow
            WHERE workflow.status IN ({workflow_placeholders})
              AND NOT EXISTS (
                  SELECT 1
                  FROM autonomous_goals AS goal
                  WHERE goal.workflow_id = workflow.workflow_id
                    AND goal.priority_class IN (?, ?)
              )
            """,
            (
                *(status.value for status in _ACTIVE_WORKFLOW_STATUSES),
                PriorityClass.P3.value,
                PriorityClass.P4.value,
            ),
        )
        return int(workflow_count or 0) > 0

    def _sync_goal_status(self, goal: GoalRecord, workflow_status: WorkflowStatus) -> None:
        terminal = _TERMINAL_WORKFLOW_TO_GOAL.get(workflow_status)
        if terminal is not None:
            target = terminal
        elif workflow_status is WorkflowStatus.PAUSED:
            target = GoalStatus.PAUSED
        else:
            target = GoalStatus.RUNNING
        if goal.status is not target:
            self.goals.update_status(goal.goal_id, target)

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            return now.replace(tzinfo=UTC)
        return now.astimezone(UTC)
