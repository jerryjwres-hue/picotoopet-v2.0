"""P4 storage maintenance is scheduled only when the existing Worker really exposes it."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from picotoopet_core.automation.models import CapabilityRegistration
from picotoopet_core.automation.repository import AutomationRepository
from picotoopet_core.automation.service import WorkflowService
from picotoopet_core.autonomous.background import AutonomousBackgroundCoordinator
from picotoopet_core.autonomous.manager import AutonomousOperationsManager
from picotoopet_core.autonomous.repository import AutonomousGoalRepository
from picotoopet_core.autonomous.storage_worker import StorageMaintenanceCoordinator
from picotoopet_core.db.database import Database
from picotoopet_core.queue.repository import QueueRepository
from picotoopet_core.worker.handlers import HandlerResult


NOW = datetime(2026, 8, 18, 7, 0, tzinfo=UTC)


class FakeRuntime:
    def __init__(self) -> None:
        self.handlers = {}


class FakeManager:
    def tick(self):  # type: ignore[no-untyped-def]
        return type(
            "Result",
            (),
            {
                "action": "idle",
                "created_goal_id": None,
                "active_goal_id": None,
                "workflow_id": None,
            },
        )()


def _handler(task) -> HandlerResult:  # type: ignore[no-untyped-def]
    return HandlerResult(summary={"task_type": task.task_type})


def _manager_stack(tmp_path: Path):  # type: ignore[no-untyped-def]
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    automation = AutomationRepository(database)
    workflows = WorkflowService(
        database,
        queue=QueueRepository(database),
        repository=automation,
    )
    manager = AutonomousOperationsManager(
        database=database,
        goals=AutonomousGoalRepository(database),
        workflows=workflows,
        clock=lambda: NOW,
    )
    return database, workflows, manager


def test_p4_workflow_adds_storage_after_diagnostics_only_when_capability_is_live(
    tmp_path: Path,
) -> None:
    database, workflows, manager = _manager_stack(tmp_path)
    workflows.capabilities.register(
        CapabilityRegistration(
            worker_id="mac-storage-worker",
            capability=StorageMaintenanceCoordinator.CAPABILITY,
            task_types=[StorageMaintenanceCoordinator.TASK_TYPE],
            healthy=True,
            heartbeat_at=NOW,
        )
    )

    result = manager.tick()
    workflow = workflows.get_workflow(result.workflow_id or "")

    assert [step.step_key for step in workflow.steps] == [
        "diagnostic-snapshot",
        "storage-maintenance",
    ]
    storage = workflow.steps[1]
    assert storage.task_type == StorageMaintenanceCoordinator.TASK_TYPE
    assert storage.required_capability == StorageMaintenanceCoordinator.CAPABILITY
    assert storage.depends_on == ["diagnostic-snapshot"]
    assert storage.payload == {"grace_hours": 24, "max_compactions": 20}
    database.close()


def test_background_coordinator_registers_injected_storage_handler_before_tick(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    router = WorkflowService(
        database,
        queue=QueueRepository(database),
        repository=AutomationRepository(database),
    ).capabilities
    runtime = FakeRuntime()
    coordinator = AutonomousBackgroundCoordinator(
        manager=FakeManager(),
        capability_router=router,
        runtime=runtime,
        worker_id="mac-worker-storage",
        local_intelligence_handler=_handler,
        storage_maintenance_handler=_handler,
        model_id="gpt-oss:20b",
        clock=lambda: NOW,
    )

    result = coordinator.tick_safely()

    assert result.succeeded is True
    assert runtime.handlers[StorageMaintenanceCoordinator.TASK_TYPE] is _handler
    registration = router.select(
        StorageMaintenanceCoordinator.CAPABILITY,
        task_type=StorageMaintenanceCoordinator.TASK_TYPE,
        now=NOW,
    )
    assert registration is not None
    assert registration.metadata["managed_root_only"] is True
    database.close()
