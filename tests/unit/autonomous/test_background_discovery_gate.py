"""P3 autonomous discovery needs both Research Gateway evidence and local screening."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from picotoopet_core.automation.capabilities import CapabilityRouter
from picotoopet_core.automation.repository import AutomationRepository
from picotoopet_core.autonomous.background import AutonomousBackgroundCoordinator
from picotoopet_core.autonomous.discovery import ContentDiscoveryCoordinator
from picotoopet_core.db.database import Database
from picotoopet_core.worker.handlers import HandlerResult


NOW = datetime(2026, 8, 18, 6, 0, tzinfo=UTC)


class FakeRuntime:
    def __init__(self) -> None:
        self.handlers = {}


class FakeManager:
    def tick(self):  # type: ignore[no-untyped-def]
        return type("Result", (), {"action": "idle", "created_goal_id": None, "active_goal_id": None, "workflow_id": None})()


def _handler(task) -> HandlerResult:  # type: ignore[no-untyped-def]
    return HandlerResult(summary={"task_type": task.task_type})


def _coordinator(tmp_path: Path):  # type: ignore[no-untyped-def]
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    router = CapabilityRouter(AutomationRepository(database))
    runtime = FakeRuntime()
    coordinator = AutonomousBackgroundCoordinator(
        manager=FakeManager(),
        capability_router=router,
        runtime=runtime,
        worker_id="mac-worker-discovery",
        local_intelligence_handler=_handler,
        content_discovery_handler=_handler,
        model_id="gpt-oss:20b",
        clock=lambda: NOW,
    )
    return database, router, runtime, coordinator


def test_local_model_health_alone_never_registers_content_discovery(tmp_path: Path) -> None:
    database, router, runtime, coordinator = _coordinator(tmp_path)

    coordinator.refresh_content_discovery(local_healthy=True, research_healthy=False)

    assert ContentDiscoveryCoordinator.TASK_TYPE not in runtime.handlers
    assert router.select(
        ContentDiscoveryCoordinator.CAPABILITY,
        task_type=ContentDiscoveryCoordinator.TASK_TYPE,
        now=NOW,
    ) is None
    database.close()


def test_research_health_alone_never_registers_content_discovery(tmp_path: Path) -> None:
    database, router, runtime, coordinator = _coordinator(tmp_path)

    coordinator.refresh_content_discovery(local_healthy=False, research_healthy=True)

    assert ContentDiscoveryCoordinator.TASK_TYPE not in runtime.handlers
    assert router.select(
        ContentDiscoveryCoordinator.CAPABILITY,
        task_type=ContentDiscoveryCoordinator.TASK_TYPE,
        now=NOW,
    ) is None
    database.close()


def test_both_healthy_register_exactly_one_content_discovery_task(tmp_path: Path) -> None:
    database, router, runtime, coordinator = _coordinator(tmp_path)

    coordinator.refresh_content_discovery(local_healthy=True, research_healthy=True)

    assert runtime.handlers[ContentDiscoveryCoordinator.TASK_TYPE] is _handler
    registration = router.select(
        ContentDiscoveryCoordinator.CAPABILITY,
        task_type=ContentDiscoveryCoordinator.TASK_TYPE,
        now=NOW,
    )
    assert registration is not None
    assert registration.task_types == [ContentDiscoveryCoordinator.TASK_TYPE]
    assert registration.metadata["pipeline"] == "research-gateway-then-local-scout"
    assert registration.metadata["read_only"] is True
    database.close()


def test_lost_health_withdraws_handler_and_capability(tmp_path: Path) -> None:
    database, router, runtime, coordinator = _coordinator(tmp_path)
    coordinator.refresh_content_discovery(local_healthy=True, research_healthy=True)

    coordinator.refresh_content_discovery(local_healthy=False, research_healthy=True)

    assert ContentDiscoveryCoordinator.TASK_TYPE not in runtime.handlers
    assert router.select(
        ContentDiscoveryCoordinator.CAPABILITY,
        task_type=ContentDiscoveryCoordinator.TASK_TYPE,
        now=NOW,
    ) is None
    record = next(
        item for item in router.list()
        if item.worker_id == "mac-worker-discovery"
        and item.capability == ContentDiscoveryCoordinator.CAPABILITY
    )
    assert record.healthy is False
    assert record.task_types == []
    database.close()
