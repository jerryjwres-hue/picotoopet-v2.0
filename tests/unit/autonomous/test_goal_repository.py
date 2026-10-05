"""Durable Goal facts must extend, not duplicate, the existing workflow/queue model."""

from __future__ import annotations

from pathlib import Path

from picotoopet_core.autonomous.models import (
    GoalCreate,
    GoalOrigin,
    GoalStatus,
    PriorityClass,
)
from picotoopet_core.autonomous.repository import AutonomousGoalRepository
from picotoopet_core.db.database import Database


def _open_database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def _request(*, key: str = "goal:nightly-content-radar") -> GoalCreate:
    return GoalCreate(
        origin=GoalOrigin.AUTONOMOUS,
        intent_type="content.discover",
        priority_class=PriorityClass.P3,
        objective="发现近期高增长的宠物内容主题",
        constraints={"market": "US", "read_only": True},
        budget_class="local-first",
        pinned=False,
        idempotency_key=key,
    )


def test_priority_classes_map_to_existing_queue_priority_range() -> None:
    assert PriorityClass.P0.queue_priority == 0
    assert PriorityClass.P1.queue_priority == 100
    assert PriorityClass.P2.queue_priority == 300
    assert PriorityClass.P3.queue_priority == 600
    assert PriorityClass.P4.queue_priority == 900


def test_goal_creation_is_idempotent_and_does_not_create_a_second_queue(tmp_path: Path) -> None:
    database = _open_database(tmp_path)
    repository = AutonomousGoalRepository(database)

    first = repository.create(_request())
    second = repository.create(_request())

    assert second.goal_id == first.goal_id
    assert first.status is GoalStatus.READY
    assert first.workflow_id is None
    assert database.scalar("SELECT COUNT(*) FROM autonomous_goals") == 1
    assert database.scalar("SELECT COUNT(*) FROM tasks") == 0
    assert database.scalar("SELECT COUNT(*) FROM workflow_runs") == 0
    # Schema retention gate      Goal facts survive current schema 23.
    assert database.scalar("SELECT MAX(version) FROM schema_migrations") == 23
    database.close()


def test_goal_replays_after_restart_and_can_bind_existing_workflow(tmp_path: Path) -> None:
    database = _open_database(tmp_path)
    repository = AutonomousGoalRepository(database)
    created = repository.create(_request(key="goal:restart"))
    repository.bind_workflow(created.goal_id, "workflow-existing-123")
    repository.update_status(created.goal_id, GoalStatus.RUNNING)
    database.close()

    reopened = _open_database(tmp_path)
    replayed = AutonomousGoalRepository(reopened).get(created.goal_id)

    assert replayed.goal_id == created.goal_id
    assert replayed.workflow_id == "workflow-existing-123"
    assert replayed.priority_class is PriorityClass.P3
    assert replayed.origin is GoalOrigin.AUTONOMOUS
    assert replayed.status is GoalStatus.RUNNING
    assert replayed.constraints == {"market": "US", "read_only": True}
    reopened.close()


def test_goal_list_preserves_parent_pin_score_and_priority(tmp_path: Path) -> None:
    database = _open_database(tmp_path)
    repository = AutonomousGoalRepository(database)
    parent = repository.create(
        GoalCreate(
            origin=GoalOrigin.HUMAN,
            intent_type="product.research",
            priority_class=PriorityClass.P1,
            objective="研究目标产品",
            budget_class="local-first",
            pinned=True,
            idempotency_key="goal:parent",
        )
    )
    child = repository.create(
        GoalCreate(
            origin=GoalOrigin.SYSTEM,
            intent_type="evidence.complete",
            priority_class=PriorityClass.P2,
            objective="补齐缺失证据",
            parent_goal_id=parent.goal_id,
            score=88.5,
            idempotency_key="goal:child",
        )
    )

    rows = repository.list(limit=10)
    by_id = {item.goal_id: item for item in rows}

    assert by_id[parent.goal_id].pinned is True
    assert by_id[child.goal_id].parent_goal_id == parent.goal_id
    assert by_id[child.goal_id].score == 88.5
    assert by_id[child.goal_id].priority_class is PriorityClass.P2
    database.close()
