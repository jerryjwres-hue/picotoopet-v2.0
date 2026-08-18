"""The autonomous manager must feed the existing workflow system without competing with it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from picotoopet_core.automation.models import CapabilityRegistration, WorkflowStatus
from picotoopet_core.automation.repository import AutomationRepository
from picotoopet_core.automation.service import WorkflowService
from picotoopet_core.autonomous.manager import AutonomousOperationsManager
from picotoopet_core.autonomous.models import PriorityClass
from picotoopet_core.autonomous.repository import AutonomousGoalRepository
from picotoopet_core.db.database import Database
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.queue.repository import QueueRepository


NOW = datetime(2026, 8, 18, 2, 0, tzinfo=UTC)


def _stack(tmp_path: Path):  # type: ignore[no-untyped-def]
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    queue = QueueRepository(database)
    automation = AutomationRepository(database)
    workflows = WorkflowService(database, queue=queue, repository=automation)
    goals = AutonomousGoalRepository(database)
    manager = AutonomousOperationsManager(
        database=database,
        goals=goals,
        workflows=workflows,
        clock=lambda: NOW,
    )
    return database, queue, automation, workflows, goals, manager


def test_explicit_active_queue_work_suppresses_autonomous_creation(tmp_path: Path) -> None:
    database, queue, _automation, _workflows, goals, manager = _stack(tmp_path)
    queue.create(
        TaskCreate(
            task_type="system.noop",
            payload={"origin": "human"},
            priority=PriorityClass.P1.queue_priority,
            idempotency_key="human:active",
        )
    )

    result = manager.tick()

    assert result.action == "yield_explicit_work"
    assert result.created_goal_id is None
    assert goals.list() == []
    assert database.scalar("SELECT COUNT(*) FROM workflow_runs") == 0
    database.close()


def test_idle_tick_creates_one_restart_safe_p4_maintenance_workflow(tmp_path: Path) -> None:
    database, _queue, _automation, workflows, goals, manager = _stack(tmp_path)

    first = manager.tick()
    second = manager.tick()

    assert first.action == "created_maintenance"
    assert second.action == "reconciled_autonomous"
    assert first.created_goal_id == second.active_goal_id
    assert database.scalar("SELECT COUNT(*) FROM autonomous_goals") == 1
    assert database.scalar("SELECT COUNT(*) FROM workflow_runs") == 1
    goal = goals.get(first.created_goal_id or "")
    workflow = workflows.get_workflow(goal.workflow_id or "")
    assert goal.priority_class is PriorityClass.P4
    assert workflow.priority == PriorityClass.P4.queue_priority
    assert workflow.max_concurrency == 1
    assert workflow.status is WorkflowStatus.RUNNING
    assert workflow.steps[0].task_type == "system.diagnostic_snapshot"
    database.close()

    # A new process over the same Core database reuses the durable Goal/workflow.
    reopened = Database(tmp_path / "core.db")
    reopened.open()
    reopened.apply_migrations()
    reopened_automation = AutomationRepository(reopened)
    reopened_workflows = WorkflowService(
        reopened,
        queue=QueueRepository(reopened),
        repository=reopened_automation,
    )
    restarted = AutonomousOperationsManager(
        database=reopened,
        goals=AutonomousGoalRepository(reopened),
        workflows=reopened_workflows,
        clock=lambda: NOW,
    ).tick()
    assert restarted.action == "reconciled_autonomous"
    assert reopened.scalar("SELECT COUNT(*) FROM autonomous_goals") == 1
    assert reopened.scalar("SELECT COUNT(*) FROM workflow_runs") == 1
    reopened.close()


def test_fresh_discovery_capability_prefers_p3_over_maintenance(tmp_path: Path) -> None:
    database, _queue, automation, workflows, goals, manager = _stack(tmp_path)
    workflows.capabilities.register(
        CapabilityRegistration(
            worker_id="mac-content-discovery",
            capability="content.discovery",
            task_types=["autonomous.discovery.v1"],
            healthy=True,
            heartbeat_at=NOW,
        )
    )

    result = manager.tick()

    assert result.action == "created_discovery"
    goal = goals.get(result.created_goal_id or "")
    workflow = workflows.get_workflow(goal.workflow_id or "")
    assert goal.priority_class is PriorityClass.P3
    assert workflow.priority == PriorityClass.P3.queue_priority
    assert workflow.max_concurrency == 1
    assert workflow.steps[0].task_type == "autonomous.discovery.v1"
    assert workflow.steps[0].required_capability == "content.discovery"
    assert automation.list_capabilities()[0].worker_id == "mac-content-discovery"
    database.close()


def test_stale_discovery_capability_falls_back_to_p4(tmp_path: Path) -> None:
    database, _queue, _automation, workflows, goals, manager = _stack(tmp_path)
    workflows.capabilities.register(
        CapabilityRegistration(
            worker_id="stale-content-discovery",
            capability="content.discovery",
            task_types=["autonomous.discovery.v1"],
            healthy=True,
            heartbeat_at=NOW - timedelta(minutes=3),
        )
    )

    result = manager.tick()

    assert result.action == "created_maintenance"
    assert goals.get(result.created_goal_id or "").priority_class is PriorityClass.P4
    database.close()
