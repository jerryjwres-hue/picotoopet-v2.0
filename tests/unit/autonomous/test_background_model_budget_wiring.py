"""Managed autonomous synthesis must receive the worker's single live model budget provider."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from picotoopet_core.automation.capabilities import CapabilityRouter
from picotoopet_core.automation.repository import AutomationRepository
from picotoopet_core.autonomous.background import AutonomousBackgroundCoordinator
from picotoopet_core.autonomous.human_pipeline import GoalSynthesisCoordinator
from picotoopet_core.autonomous.local_intelligence import (
    LocalAnalysisRequest,
    LocalAnalysisResult,
    LocalIntelligenceCoordinator,
)
from picotoopet_core.db.database import Database
from picotoopet_core.ollama.budget import ModelInputBudget


NOW = datetime(2026, 8, 20, 17, 40, tzinfo=UTC)


class _Adapter:
    def analyze(self, request: LocalAnalysisRequest) -> LocalAnalysisResult:
        return LocalAnalysisResult(
            role=request.role,
            summary="bounded",
            confidence=0.8,
            findings=[],
            recommended_actions=[],
            evidence_ids=request.evidence_ids,
        )


class _Runtime:
    def __init__(self) -> None:
        self.handlers = {}
        self.result_store = object()


class _Manager:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.goals = object()
        self.workflows = object()

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


class _BudgetProvider:
    def __call__(self, estimated_tokens: int) -> ModelInputBudget:
        return ModelInputBudget(
            estimated_tokens=estimated_tokens,
            memory_pressure="warn",
            loaded_model_count=1,
            max_estimated_tokens=4_312,
            max_input_chars=17_248,
            max_concurrency=1,
            requires_chunking=estimated_tokens > 4_312,
        )


def test_managed_goal_synthesis_reuses_injected_model_budget_provider(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    database = Database(runtime_root / "database" / "core.db")
    database.open()
    database.apply_migrations()
    router = CapabilityRouter(AutomationRepository(database))
    runtime = _Runtime()
    local = LocalIntelligenceCoordinator(_Adapter())
    provider = _BudgetProvider()

    coordinator = AutonomousBackgroundCoordinator(
        manager=_Manager(database),
        capability_router=router,
        runtime=runtime,
        worker_id="mac-worker-budget-wiring",
        local_intelligence_handler=local.handler,
        model_input_budget=provider,
        model_id="gpt-oss:20b",
        clock=lambda: NOW,
    )
    try:
        handler = coordinator.goal_synthesis_handler
        assert handler is not None
        owner = getattr(handler, "__self__", None)
        assert isinstance(owner, GoalSynthesisCoordinator)
        assert owner.input_budget is provider
    finally:
        database.close()
