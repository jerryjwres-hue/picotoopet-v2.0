from __future__ import annotations

import hashlib
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from picotoopet_core.autonomous.human_pipeline import (
    GoalHandoffCoordinator,
    GoalPipelineError,
    GoalSynthesisCoordinator,
    HumanGoalWorkflowPlanner,
)
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
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskRecord


def _goal(intent_type: str = "product.research_to_video") -> GoalRecord:
    now = datetime.now(UTC)
    return GoalRecord(
        goal_id="goal-123",
        workflow_id="workflow-123",
        origin=GoalOrigin.HUMAN,
        intent_type=intent_type,
        priority_class=PriorityClass.P1,
        objective="研究大型犬耐咬玩具的消费者痛点，并生成 TikTok AI 视频方案",
        constraints={
            "depth": "standard",
            "external_ai_upload_requires_user_action": True,
            "read_only_research": True,
        },
        budget_class="local-first",
        pinned=False,
        score=None,
        status=GoalStatus.READY,
        idempotency_key="human:test-goal",
        created_at=now,
        updated_at=now,
    )


def _task(task_type: str, *, payload: dict[str, object]) -> TaskRecord:
    now = datetime.now(UTC)
    return TaskRecord(
        task_id="current-task",
        task_type=task_type,
        status=TaskStatus.RUNNING,
        priority=100,
        resource_tag="workflow:workflow-123",
        payload=payload,
        attempt_count=1,
        max_attempts=1,
        timeout_seconds=900,
        created_at=now,
        updated_at=now,
    )


class FakeGoals:
    def __init__(self, goal: GoalRecord) -> None:
        self.goal = goal

    def get(self, goal_id: str) -> GoalRecord:
        assert goal_id == self.goal.goal_id
        return self.goal


class FakeWorkflows:
    def __init__(self, *, discovery_task_id: str = "discovery-task", synthesis_task_id: str = "synthesis-task") -> None:
        self.record = SimpleNamespace(
            workflow_id="workflow-123",
            steps=[
                SimpleNamespace(step_key="research-evidence", task_id=discovery_task_id),
                SimpleNamespace(step_key="evidence-synthesis", task_id=synthesis_task_id),
                SimpleNamespace(step_key="web-gpt-handoff", task_id="handoff-task"),
            ],
        )

    def get_workflow(self, workflow_id: str):  # type: ignore[no-untyped-def]
        assert workflow_id == self.record.workflow_id
        return self.record


class FakeResultRecords:
    def __init__(self, mapping: dict[str, tuple[str, str]]) -> None:
        self.mapping = mapping

    def get_for_task(self, task_id: str):  # type: ignore[no-untyped-def]
        object_hash, result_type = self.mapping[task_id]
        return SimpleNamespace(object_hash=object_hash, result_type=result_type)


class FakeResultStore:
    def __init__(self, documents: dict[str, dict[str, object]]) -> None:
        self.documents = documents

    def read_json(self, object_hash: str, *, max_bytes: int) -> dict[str, object]:
        assert max_bytes <= 256 * 1024
        return self.documents[object_hash]


class FakeLocal:
    def __init__(self) -> None:
        self.requests = []

    def analyze(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return LocalAnalysisResult(
            role=LocalAnalysisRole.ANALYST,
            summary="耐久性和尺寸预期是主要决策点。",
            confidence=0.82,
            findings=["消费者反复讨论耐咬寿命", "大型犬用户担心尺寸和吞咽风险"],
            recommended_actions=["创意先证明耐用场景，再展示尺寸参照"],
            evidence_ids=["search-01", "search-02"],
        )


def _discovery_document() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "objective": "研究大型犬耐咬玩具",
        "summary": "公开资料显示耐用性、尺寸和安全是高频主题。",
        "confidence": 0.78,
        "findings": ["耐久性主题", "尺寸主题"],
        "recommended_actions": ["继续验证大型犬场景"],
        "evidence_ids": ["search-01", "search-02"],
        "search_evidence": [
            {
                "evidence_id": "search-01",
                "query": "大型犬 耐咬 玩具 痛点",
                "output_excerpt": "用户讨论耐咬寿命以及碎裂问题。",
            },
            {
                "evidence_id": "search-02",
                "query": "large dog durable toy complaints",
                "output_excerpt": "Owners discuss size fit and choking concerns.",
            },
        ],
        "content_radar": {
            "research_stop": {"stop": True, "reason": "low_information_gain", "next_round": None}
        },
    }


def _synthesis_document() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "goal_id": "goal-123",
        "executive_summary": "耐久性和尺寸预期是主要决策点。",
        "confidence": 0.82,
        "findings": ["消费者反复讨论耐咬寿命", "大型犬用户担心尺寸和吞咽风险"],
        "recommended_actions": ["创意先证明耐用场景，再展示尺寸参照"],
        "evidence_ids": ["search-01", "search-02"],
        "research_stop_reason": "low_information_gain",
    }


def test_workflow_planner_uses_only_fixed_server_owned_steps() -> None:
    plan = HumanGoalWorkflowPlanner().plan(_goal())
    assert plan.priority == PriorityClass.P1.queue_priority
    assert plan.max_concurrency == 1
    assert [step.step_key for step in plan.steps] == [
        "research-evidence",
        "evidence-synthesis",
        "web-gpt-handoff",
    ]
    assert [step.task_type for step in plan.steps] == [
        "autonomous.discovery.v1",
        "autonomous.goal_synthesis.v1",
        "autonomous.goal_handoff.v1",
    ]
    assert plan.steps[0].required_capability == "content.discovery"
    assert plan.steps[1].required_capability == "local.goal.synthesis"
    assert plan.steps[2].required_capability == "local.goal.handoff"
    assert plan.steps[1].depends_on == ["research-evidence"]
    assert plan.steps[2].depends_on == ["evidence-synthesis"]
    assert plan.steps[1].payload == {"goal_id": "goal-123"}
    assert plan.steps[2].payload == {"goal_id": "goal-123"}

    research_only = HumanGoalWorkflowPlanner().plan(_goal("product.research"))
    assert [step.step_key for step in research_only.steps] == [
        "research-evidence",
        "evidence-synthesis",
    ]


def test_synthesis_reads_real_discovery_result_instead_of_task_payload_text() -> None:
    discovery = _discovery_document()
    local = FakeLocal()
    coordinator = GoalSynthesisCoordinator(
        goals=FakeGoals(_goal()),
        workflows=FakeWorkflows(),
        result_records=FakeResultRecords(
            {"discovery-task": ("d" * 64, "autonomous.discovery.v1")}
        ),
        result_store=FakeResultStore({"d" * 64: discovery}),
        local=local,
    )

    result = coordinator.handler(
        _task(
            "autonomous.goal_synthesis.v1",
            payload={"goal_id": "goal-123"},
        )
    )
    assert len(local.requests) == 1
    request = local.requests[0]
    assert request.role is LocalAnalysisRole.ANALYST
    assert "用户讨论耐咬寿命以及碎裂问题" in request.text
    assert request.evidence_ids == ["search-01", "search-02"]
    assert result.result_document is not None
    assert result.result_document["goal_id"] == "goal-123"
    assert result.result_document["executive_summary"] == "耐久性和尺寸预期是主要决策点。"
    assert result.result_document["research_stop_reason"] == "low_information_gain"


def test_synthesis_refuses_to_invent_when_discovery_result_is_missing() -> None:
    coordinator = GoalSynthesisCoordinator(
        goals=FakeGoals(_goal()),
        workflows=FakeWorkflows(discovery_task_id="missing"),
        result_records=FakeResultRecords({}),
        result_store=FakeResultStore({}),
        local=FakeLocal(),
    )
    with pytest.raises(GoalPipelineError, match="discovery result"):
        coordinator.handler(
            _task("autonomous.goal_synthesis.v1", payload={"goal_id": "goal-123"})
        )


def test_handoff_uses_prior_results_and_returns_no_local_path(tmp_path: Path) -> None:
    discovery = _discovery_document()
    synthesis = _synthesis_document()
    coordinator = GoalHandoffCoordinator(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        goals=FakeGoals(_goal()),
        workflows=FakeWorkflows(),
        result_records=FakeResultRecords(
            {
                "discovery-task": ("d" * 64, "autonomous.discovery.v1"),
                "synthesis-task": ("s" * 64, "autonomous.goal_synthesis.v1"),
            }
        ),
        result_store=FakeResultStore(
            {"d" * 64: discovery, "s" * 64: synthesis}
        ),
    )

    result = coordinator.handler(
        _task("autonomous.goal_handoff.v1", payload={"goal_id": "goal-123"})
    )
    assert result.result_document is not None
    document = result.result_document
    assert document["goal_id"] == "goal-123"
    assert document["handoff_ready"] is True
    assert document["manual_web_gpt_upload_required"] is True
    assert document["prompt_version"] == "web-gpt-master-v1.0"
    assert "/" not in document["package_name"]
    assert "\\" not in document["package_name"]
    assert "local_path" not in document
    assert len(document["package_sha256"]) == 64

    package = RuntimePaths.from_root(tmp_path / "runtime").autonomous_handoffs_dir / document["package_name"]
    assert package.is_file()
    assert hashlib.sha256(package.read_bytes()).hexdigest() == document["package_sha256"]
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        assert "WEB_GPT_MASTER_PROMPT.txt" in names
        assert "HANDOFF_MANIFEST.json" in names
        evidence = archive.read("04_EVIDENCE.md").decode("utf-8")
        assert "用户讨论耐咬寿命以及碎裂问题" in evidence
