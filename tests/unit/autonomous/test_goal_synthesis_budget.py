"""Goal synthesis must honor adaptive local-model input budgets before inference."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from picotoopet_core.autonomous.human_pipeline import GoalSynthesisCoordinator
from picotoopet_core.autonomous.local_intelligence import (
    LocalAnalysisResult,
    LocalAnalysisRole,
)
from picotoopet_core.autonomous.models import (
    GoalOrigin,
    GoalRecord,
    GoalStatus,
    PriorityClass,
)
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.ollama.budget import ModelInputBudget


def _goal() -> GoalRecord:
    now = datetime.now(UTC)
    return GoalRecord(
        goal_id="goal-budget",
        workflow_id="workflow-budget",
        origin=GoalOrigin.HUMAN,
        intent_type="product.research",
        priority_class=PriorityClass.P1,
        objective="综合大量研究证据但不要扩大本地模型上下文",
        constraints={"depth": "standard", "read_only_research": True},
        budget_class="local-first",
        pinned=False,
        score=None,
        status=GoalStatus.READY,
        idempotency_key="human:budget-test",
        created_at=now,
        updated_at=now,
    )


def _task() -> TaskRecord:
    now = datetime.now(UTC)
    return TaskRecord(
        task_id="synthesis-task",
        task_type="autonomous.goal_synthesis.v1",
        status=TaskStatus.RUNNING,
        priority=100,
        resource_tag="workflow:workflow-budget",
        payload={"goal_id": "goal-budget"},
        attempt_count=1,
        max_attempts=2,
        timeout_seconds=600,
        created_at=now,
        updated_at=now,
    )


class _Goals:
    def get(self, goal_id: str) -> GoalRecord:
        assert goal_id == "goal-budget"
        return _goal()


class _Workflows:
    def get_workflow(self, workflow_id: str):  # type: ignore[no-untyped-def]
        assert workflow_id == "workflow-budget"
        return SimpleNamespace(
            workflow_id=workflow_id,
            steps=[SimpleNamespace(step_key="research-evidence", task_id="discovery-task")],
        )


class _ResultRecords:
    def get_for_task(self, task_id: str):  # type: ignore[no-untyped-def]
        assert task_id == "discovery-task"
        return SimpleNamespace(
            object_hash="d" * 64,
            result_type="autonomous.discovery.v1",
        )


class _ResultStore:
    def read_json(self, object_hash: str, *, max_bytes: int):  # type: ignore[no-untyped-def]
        assert object_hash == "d" * 64
        assert max_bytes <= 256 * 1024
        evidence_ids = [f"search-{index:02d}" for index in range(1, 5)]
        return {
            "schema_version": "1.0",
            "summary": "已有研究证据需要分块综合。",
            "evidence_ids": evidence_ids,
            "search_evidence": [
                {
                    "evidence_id": evidence_id,
                    "query": f"query {index}",
                    "output_excerpt": (f"evidence-{index} " * 700),
                }
                for index, evidence_id in enumerate(evidence_ids, start=1)
            ],
            "content_radar": {
                "research_stop": {
                    "stop": True,
                    "reason": "low_information_gain",
                    "next_round": None,
                }
            },
        }


class _RecordingLocal:
    def __init__(self) -> None:
        self.requests = []

    def analyze(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return LocalAnalysisResult(
            role=request.role,
            summary=(
                "最终预算内综合结论。"
                if request.role is LocalAnalysisRole.EDITOR
                else "分块分析结论。"
            ),
            confidence=0.8,
            findings=["预算内证据模式"],
            recommended_actions=["保持串行本地分析"],
            evidence_ids=request.evidence_ids,
        )


class _FixedBudget:
    def __init__(self) -> None:
        self.estimated_tokens: list[int] = []

    def __call__(self, estimated_tokens: int) -> ModelInputBudget:
        self.estimated_tokens.append(estimated_tokens)
        return ModelInputBudget(
            estimated_tokens=estimated_tokens,
            memory_pressure="high",
            loaded_model_count=1,
            max_estimated_tokens=1_500,
            max_input_chars=6_000,
            max_concurrency=1,
            requires_chunking=True,
        )


def test_synthesis_chunks_before_model_calls_and_merges_serially() -> None:
    local = _RecordingLocal()
    budget = _FixedBudget()
    coordinator = GoalSynthesisCoordinator(
        goals=_Goals(),
        workflows=_Workflows(),
        result_records=_ResultRecords(),
        result_store=_ResultStore(),
        local=local,
        input_budget=budget,
    )

    result = coordinator.handler(_task())

    assert budget.estimated_tokens
    analyst_requests = [
        request for request in local.requests if request.role is LocalAnalysisRole.ANALYST
    ]
    assert len(analyst_requests) >= 2
    assert all(len(request.text) <= 6_000 for request in local.requests)
    assert local.requests[-1].role is LocalAnalysisRole.EDITOR
    assert result.result_document is not None
    assert result.result_document["executive_summary"] == "最终预算内综合结论。"
