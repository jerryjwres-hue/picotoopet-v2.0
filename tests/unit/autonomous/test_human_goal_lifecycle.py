"""Human Goal status must stay a truthful projection of the canonical Workflow fact."""

from __future__ import annotations

from pathlib import Path

from picotoopet_core.automation.service import WorkflowService
from picotoopet_core.autonomous.goal_service import (
    HumanGoalRequest,
    HumanGoalService,
    HumanGoalType,
)
from picotoopet_core.autonomous.models import GoalStatus
from picotoopet_core.autonomous.repository import AutonomousGoalRepository
from picotoopet_core.db.database import Database


def _stack(tmp_path: Path):  # type: ignore[no-untyped-def]
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    goals = AutonomousGoalRepository(database)
    workflows = WorkflowService(database)
    service = HumanGoalService(goals, workflows)
    return database, goals, workflows, service


def test_get_projects_running_and_terminal_workflow_status_into_human_goal(tmp_path: Path) -> None:
    database, goals, _workflows, service = _stack(tmp_path)
    goal = service.create(
        HumanGoalRequest(
            goal_type=HumanGoalType.PRODUCT_RESEARCH,
            objective="研究大型犬耐咬玩具",
        ),
        idempotency_key="human-lifecycle-running",
    )
    assert goal.workflow_id is not None
    assert goal.status is GoalStatus.READY

    database.execute(
        "UPDATE workflow_runs SET status = 'Running' WHERE workflow_id = ?",
        (goal.workflow_id,),
    )
    running = service.get(goal.goal_id)
    assert running.status is GoalStatus.RUNNING
    assert goals.get(goal.goal_id).status is GoalStatus.RUNNING

    database.execute(
        "UPDATE workflow_runs SET status = 'Completed' WHERE workflow_id = ?",
        (goal.workflow_id,),
    )
    completed = service.get(goal.goal_id)
    assert completed.status is GoalStatus.COMPLETED
    assert goals.get(goal.goal_id).status is GoalStatus.COMPLETED
    database.close()


def test_list_projects_needs_attention_as_deferred_without_inventing_failure(tmp_path: Path) -> None:
    database, goals, _workflows, service = _stack(tmp_path)
    goal = service.create(
        HumanGoalRequest(
            goal_type=HumanGoalType.PRODUCT_RESEARCH_TO_VIDEO,
            objective="研究产品并生成视频交接包",
        ),
        idempotency_key="human-lifecycle-attention",
    )
    assert goal.workflow_id is not None

    database.execute(
        "UPDATE workflow_runs SET status = 'NeedsAttention' WHERE workflow_id = ?",
        (goal.workflow_id,),
    )
    listed = {item.goal_id: item for item in service.list(limit=50)}

    assert listed[goal.goal_id].status is GoalStatus.DEFERRED
    assert goals.get(goal.goal_id).status is GoalStatus.DEFERRED
    database.close()
