"""The existing local-intelligence coordinator is reused for tool-first discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from picotoopet_core.automation.capabilities import CapabilityRouter
from picotoopet_core.automation.repository import AutomationRepository
from picotoopet_core.autonomous.background import AutonomousBackgroundCoordinator
from picotoopet_core.autonomous.discovery import ContentDiscoveryCoordinator
from picotoopet_core.autonomous.local_intelligence import (
    LocalAnalysisRequest,
    LocalAnalysisResult,
    LocalIntelligenceCoordinator,
)
from picotoopet_core.db.database import Database


NOW = datetime(2026, 8, 18, 6, 15, tzinfo=UTC)


class FakeAdapter:
    def analyze(self, request: LocalAnalysisRequest) -> LocalAnalysisResult:
        return LocalAnalysisResult(
            role=request.role,
            summary="bounded",
            confidence=0.8,
            findings=[],
            recommended_actions=[],
            evidence_ids=request.evidence_ids,
        )


class FakeRuntime:
    def __init__(self) -> None:
        self.handlers = {}


class FakeManager:
    def tick(self):  # type: ignore[no-untyped-def]
        return type("Result", (), {"action": "idle", "created_goal_id": None, "active_goal_id": None, "workflow_id": None})()


def test_bound_local_coordinator_auto_builds_discovery_with_cached_research_probe(tmp_path: Path) -> None:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    router = CapabilityRouter(AutomationRepository(database))
    runtime = FakeRuntime()
    local = LocalIntelligenceCoordinator(FakeAdapter())
    probe_calls = 0
    monotonic_value = 100.0

    def research_probe() -> bool:
        nonlocal probe_calls
        probe_calls += 1
        return True

    coordinator = AutonomousBackgroundCoordinator(
        manager=FakeManager(),
        capability_router=router,
        runtime=runtime,
        worker_id="mac-worker-auto-bind",
        local_intelligence_handler=local.handler,
        research_probe=research_probe,
        model_id="gpt-oss:20b",
        clock=lambda: NOW,
        monotonic=lambda: monotonic_value,
        research_probe_interval_seconds=15.0,
    )

    coordinator.refresh_local_intelligence(healthy=True)
    coordinator.refresh_local_intelligence(healthy=True)

    assert runtime.handlers[LocalIntelligenceCoordinator.TASK_TYPE] == local.handler
    assert ContentDiscoveryCoordinator.TASK_TYPE in runtime.handlers
    registration = router.select(
        ContentDiscoveryCoordinator.CAPABILITY,
        task_type=ContentDiscoveryCoordinator.TASK_TYPE,
        now=NOW,
    )
    assert registration is not None
    assert probe_calls == 1
    database.close()
