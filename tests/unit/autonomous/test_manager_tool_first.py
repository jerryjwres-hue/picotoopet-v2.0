"""A healthy language model alone must never invent autonomous discovery facts."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from picotoopet_core.automation.models import CapabilityRegistration
from picotoopet_core.automation.repository import AutomationRepository
from picotoopet_core.automation.service import WorkflowService
from picotoopet_core.autonomous.manager import AutonomousOperationsManager
from picotoopet_core.autonomous.models import PriorityClass
from picotoopet_core.autonomous.repository import AutonomousGoalRepository
from picotoopet_core.db.database import Database
from picotoopet_core.queue.repository import QueueRepository


NOW = datetime(2026, 8, 18, 4, 30, tzinfo=UTC)


def _stack(tmp_path: Path):  # type: ignore[no-untyped-def]
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    automation = AutomationRepository(database)
    workflows = WorkflowService(
        database,
        queue=QueueRepository(database),
        repository=automation,
    )
    goals = AutonomousGoalRepository(database)
    manager = AutonomousOperationsManager(
        database=database,
        goals=goals,
        workflows=workflows,
        clock=lambda: NOW,
    )
    return database, workflows, goals, manager


def test_local_text_model_alone_falls_back_to_maintenance(tmp_path: Path) -> None:
    database, workflows, goals, manager = _stack(tmp_path)
    workflows.capabilities.register(
        CapabilityRegistration(
            worker_id="mac-local-llm",
            capability="local.text.analysis",
            task_types=["autonomous.local_analysis.v1"],
            healthy=True,
            heartbeat_at=NOW,
        )
    )

    result = manager.tick()

    assert result.action == "created_maintenance"
    assert goals.get(result.created_goal_id or "").priority_class is PriorityClass.P4
    database.close()


def test_real_discovery_capability_is_required_for_p3_creation(tmp_path: Path) -> None:
    database, workflows, goals, manager = _stack(tmp_path)
    workflows.capabilities.register(
        CapabilityRegistration(
            worker_id="mac-research-discovery",
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
    assert workflow.steps[0].task_type == "autonomous.discovery.v1"
    assert workflow.steps[0].required_capability == "content.discovery"
    database.close()
