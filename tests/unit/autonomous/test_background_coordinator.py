"""Autonomous background work must share the existing Worker process safely."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from picotoopet_core.automation.capabilities import CapabilityRouter
from picotoopet_core.automation.repository import AutomationRepository
from picotoopet_core.autonomous.background import AutonomousBackgroundCoordinator
from picotoopet_core.autonomous.human_pipeline import (
    GoalHandoffCoordinator,
    GoalSynthesisCoordinator,
)
from picotoopet_core.autonomous.local_intelligence import LocalIntelligenceCoordinator
from picotoopet_core.db.database import Database
from picotoopet_core.worker.handlers import HandlerResult


NOW = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)


class FakeRuntime:
    def __init__(self) -> None:
        self.handlers = {"system.noop": lambda task: HandlerResult(summary={})}


class FakeManager:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def tick(self):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.fail:
            raise RuntimeError("simulated autonomous failure")

        class Result:
            action = "created_maintenance"
            created_goal_id = "goal-1"
            active_goal_id = "goal-1"
            workflow_id = "workflow-1"

        return Result()


def _handler(task) -> HandlerResult:  # type: ignore[no-untyped-def]
    return HandlerResult(summary={"task_type": task.task_type})


def _stack(tmp_path: Path, *, fail: bool = False):  # type: ignore[no-untyped-def]
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    router = CapabilityRouter(AutomationRepository(database))
    runtime = FakeRuntime()
    manager = FakeManager(fail=fail)
    coordinator = AutonomousBackgroundCoordinator(
        manager=manager,
        capability_router=router,
        runtime=runtime,
        worker_id="mac-worker-test",
        local_intelligence_handler=_handler,
        model_id="gpt-oss:20b",
        clock=lambda: NOW,
    )
    return database, router, runtime, manager, coordinator


def test_healthy_local_model_registers_only_fixed_analysis_task(tmp_path: Path) -> None:
    database, router, runtime, _manager, coordinator = _stack(tmp_path)

    coordinator.refresh_local_intelligence(healthy=True)

    assert runtime.handlers[LocalIntelligenceCoordinator.TASK_TYPE] is _handler
    registration = router.select(
        LocalIntelligenceCoordinator.CAPABILITY,
        task_type=LocalIntelligenceCoordinator.TASK_TYPE,
        now=NOW,
    )
    assert registration is not None
    assert registration.worker_id == "mac-worker-test"
    assert registration.metadata["model"] == "gpt-oss:20b"
    assert "autonomous.discovery.v1" not in runtime.handlers
    database.close()


def test_human_goal_pipeline_registers_fixed_synthesis_and_handoff_handlers(tmp_path: Path) -> None:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    router = CapabilityRouter(AutomationRepository(database))
    runtime = FakeRuntime()
    coordinator = AutonomousBackgroundCoordinator(
        manager=FakeManager(),
        capability_router=router,
        runtime=runtime,
        worker_id="mac-worker-test",
        local_intelligence_handler=_handler,
        goal_synthesis_handler=_handler,
        goal_handoff_handler=_handler,
        model_id="gpt-oss:20b",
        clock=lambda: NOW,
    )

    coordinator.refresh_local_intelligence(healthy=True)

    assert runtime.handlers[GoalSynthesisCoordinator.TASK_TYPE] is _handler
    assert runtime.handlers[GoalHandoffCoordinator.TASK_TYPE] is _handler
    assert router.select(
        GoalSynthesisCoordinator.CAPABILITY,
        task_type=GoalSynthesisCoordinator.TASK_TYPE,
        now=NOW,
    ) is not None
    assert router.select(
        GoalHandoffCoordinator.CAPABILITY,
        task_type=GoalHandoffCoordinator.TASK_TYPE,
        now=NOW,
    ) is not None

    coordinator.refresh_local_intelligence(healthy=False)
    assert GoalSynthesisCoordinator.TASK_TYPE not in runtime.handlers
    # Handoff is deterministic packaging and does not need the model once synthesis exists.
    assert runtime.handlers[GoalHandoffCoordinator.TASK_TYPE] is _handler
    assert router.select(
        GoalSynthesisCoordinator.CAPABILITY,
        task_type=GoalSynthesisCoordinator.TASK_TYPE,
        now=NOW,
    ) is None
    assert router.select(
        GoalHandoffCoordinator.CAPABILITY,
        task_type=GoalHandoffCoordinator.TASK_TYPE,
        now=NOW,
    ) is not None
    database.close()


def test_unhealthy_local_model_removes_handler_and_marks_capability_unhealthy(tmp_path: Path) -> None:
    database, router, runtime, _manager, coordinator = _stack(tmp_path)
    coordinator.refresh_local_intelligence(healthy=True)

    coordinator.refresh_local_intelligence(healthy=False)

    assert LocalIntelligenceCoordinator.TASK_TYPE not in runtime.handlers
    assert router.select(
        LocalIntelligenceCoordinator.CAPABILITY,
        task_type=LocalIntelligenceCoordinator.TASK_TYPE,
        now=NOW,
    ) is None
    record = next(
        item for item in router.list()
        if item.worker_id == "mac-worker-test"
        and item.capability == LocalIntelligenceCoordinator.CAPABILITY
    )
    assert record.healthy is False
    assert record.task_types == []
    database.close()


def test_autonomous_tick_exception_is_isolated_from_worker_loop(tmp_path: Path) -> None:
    database, _router, _runtime, manager, coordinator = _stack(tmp_path, fail=True)

    result = coordinator.tick_safely()

    assert manager.calls == 1
    assert result.succeeded is False
    assert result.action == "autonomous_tick_failed"
    assert result.error_code == "AUTONOMOUS_TICK_FAILED"
    assert "simulated autonomous failure" not in result.model_dump_json()
    database.close()


def test_successful_tick_returns_small_sanitized_status(tmp_path: Path) -> None:
    database, _router, _runtime, manager, coordinator = _stack(tmp_path)

    result = coordinator.tick_safely()

    assert manager.calls == 1
    assert result.succeeded is True
    assert result.action == "created_maintenance"
    assert result.goal_id == "goal-1"
    assert result.workflow_id == "workflow-1"
    assert result.error_code is None
    database.close()
