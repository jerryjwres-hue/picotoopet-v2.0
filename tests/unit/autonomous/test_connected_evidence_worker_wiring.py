"""Production-derived discovery must read the same Mac Core canonical evidence database."""

from __future__ import annotations

from pathlib import Path

from picotoopet_core.automation.capabilities import CapabilityRouter
from picotoopet_core.automation.repository import AutomationRepository
from picotoopet_core.autonomous.background import AutonomousBackgroundCoordinator
from picotoopet_core.autonomous.connected_evidence import ConnectedEvidenceRepository
from picotoopet_core.autonomous.discovery import ContentDiscoveryCoordinator
from picotoopet_core.autonomous.local_intelligence import LocalIntelligenceCoordinator
from picotoopet_core.db.database import Database


class FakeRuntime:
    def __init__(self) -> None:
        self.handlers = {}


class FakeManager:
    def __init__(self, database: Database) -> None:
        self.database = database

    def tick(self):  # type: ignore[no-untyped-def]
        raise AssertionError("scheduler tick is not part of this wiring test")


class FakeLocal:
    def analyze(self, request):  # type: ignore[no-untyped-def]
        del request
        return {
            "role": "scout",
            "summary": "fixture",
            "confidence": 0.5,
            "findings": [],
            "recommended_actions": [],
            "evidence_ids": [],
        }


def test_auto_derived_discovery_reads_same_managed_core_database(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    database = Database(runtime_root / "database" / "core.db")
    database.open()
    database.apply_migrations()
    router = CapabilityRouter(AutomationRepository(database))
    local = LocalIntelligenceCoordinator(FakeLocal())

    coordinator = AutonomousBackgroundCoordinator(
        manager=FakeManager(database),
        capability_router=router,
        runtime=FakeRuntime(),
        worker_id="mac-worker-connected-evidence",
        local_intelligence_handler=local.handler,
        model_id="gpt-oss:20b",
    )

    owner = getattr(coordinator.content_discovery_handler, "__self__", None)
    assert isinstance(owner, ContentDiscoveryCoordinator)
    assert isinstance(owner.connected_evidence, ConnectedEvidenceRepository)
    assert owner.connected_evidence.database is database
    database.close()
