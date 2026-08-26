"""Full durable Goal → Queue → Worker → Workflow → handoff regression."""

from __future__ import annotations

import zipfile
from pathlib import Path

from picotoopet_core.automation.models import CapabilityRegistration, WorkflowStatus
from picotoopet_core.automation.service import WorkflowService
from picotoopet_core.autonomous.goal_handoff_access import GoalHandoffAccess
from picotoopet_core.autonomous.goal_service import (
    HumanGoalRequest,
    HumanGoalService,
    HumanGoalType,
)
from picotoopet_core.autonomous.human_pipeline import (
    GoalHandoffCoordinator,
    GoalSynthesisCoordinator,
)
from picotoopet_core.autonomous.local_intelligence import (
    LocalAnalysisResult,
    LocalAnalysisRole,
)
from picotoopet_core.autonomous.models import GoalStatus
from picotoopet_core.autonomous.repository import AutonomousGoalRepository
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.db.database import Database
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.results.repository import ResultRepository
from picotoopet_core.results.store import ResultStore
from picotoopet_core.worker.handlers import HandlerResult
from picotoopet_core.worker.runtime import WorkerRuntime
from picotoopet_core.worker.state import WorkerStateStore


_CONNECTED_TEXT = "Strong toy, but the handle is too small for my malamute."


class DeterministicLocal:
    """No network/model dependency; returns the same evidence-linked synthesis contract."""

    def analyze(self, request):  # type: ignore[no-untyped-def]
        assert request.role is LocalAnalysisRole.ANALYST
        assert request.evidence_ids == [
            "legacy41-e2e-1",
            "search-e2e-1",
            "search-e2e-2",
        ]
        # Connected evidence must reach the second-stage analyst as bounded evidence text,
        # not disappear after the Scout/discovery stage.
        assert _CONNECTED_TEXT in request.text
        assert "Trust: B" in request.text
        return LocalAnalysisResult(
            role=LocalAnalysisRole.ANALYST,
            summary="耐久性和尺寸预期是主要购买决策点。",
            confidence=0.84,
            findings=["消费者反复讨论耐咬寿命", "大型犬用户在意尺寸和碎裂风险"],
            recommended_actions=["视频先证明耐用场景，再明确展示尺寸参照"],
            evidence_ids=request.evidence_ids,
        )


def _discovery_handler(task: TaskRecord) -> HandlerResult:
    assert task.task_type == "autonomous.discovery.v1"
    assert task.payload["read_only"] is True
    document = {
        "schema_version": "1.0",
        "objective": task.payload["objective"],
        "summary": "公开证据和旧 4.1 评论都集中在耐久性、尺寸和碎裂风险。",
        "confidence": 0.8,
        "findings": ["耐久性主题", "尺寸与碎裂主题"],
        "recommended_actions": ["继续以大型犬真实使用场景验证"],
        "evidence_ids": [
            "legacy41-e2e-1",
            "search-e2e-1",
            "search-e2e-2",
        ],
        "connected_evidence_count": 1,
        "connected_evidence": [
            {
                "evidence_id": "legacy41-e2e-1",
                "product_key": "legacy41:p-e2e",
                "evidence_type": "consumer_review",
                "source": "amazon",
                "platform": "amazon",
                "source_url": "https://www.amazon.com/dp/B0TESTE2E",
                "text_excerpt": _CONNECTED_TEXT,
                "numeric_value": None,
                "trust_level": "B",
                "confidence": 0.91,
                "captured_at": "2026-08-17T12:00:00+00:00",
                "origin": "maotai41_import",
            }
        ],
        "search_evidence": [
            {
                "evidence_id": "search-e2e-1",
                "query": "large dog durable chew toy complaints",
                "output_excerpt": "Owners repeatedly discuss durability and fragments.",
            },
            {
                "evidence_id": "search-e2e-2",
                "query": "大型犬 耐咬 玩具 尺寸 痛点",
                "output_excerpt": "消费者关注尺寸是否适合大型犬，以及碎裂后的吞咽风险。",
            },
        ],
        "content_radar": {
            "research_stop": {
                "stop": True,
                "reason": "low_information_gain",
                "next_round": None,
            }
        },
    }
    return HandlerResult(
        summary={"task_type": task.task_type, "evidence_count": 3},
        result_document=document,
        result_type="autonomous.discovery.v1",
        schema_version="1.0",
    )


def _register_capabilities(workflows: WorkflowService) -> None:
    for capability, task_type in (
        ("content.discovery", "autonomous.discovery.v1"),
        ("local.goal.synthesis", "autonomous.goal_synthesis.v1"),
        ("local.goal.handoff", "autonomous.goal_handoff.v1"),
    ):
        workflows.capabilities.register(
            CapabilityRegistration(
                worker_id="goal-e2e-worker",
                capability=capability,
                task_types=[task_type],
                healthy=True,
                metadata={"test": "deterministic-e2e"},
            )
        )


def test_human_video_goal_runs_all_three_worker_stages_and_exposes_verified_handoff(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    database = Database(paths.database_file)
    database.open()
    database.apply_migrations()
    queue = DiagnosticQueueRepository(database)
    workflows = WorkflowService(database, queue=queue)
    goals = AutonomousGoalRepository(database)
    result_store = ResultStore(paths.results_dir)
    result_records = ResultRepository(database)
    _register_capabilities(workflows)

    goal_service = HumanGoalService(goals, workflows)
    goal = goal_service.create(
        HumanGoalRequest(
            goal_type=HumanGoalType.PRODUCT_RESEARCH_TO_VIDEO,
            objective="研究大型犬耐咬玩具的消费者痛点，并生成 TikTok AI 视频方案",
        ),
        idempotency_key="human-goal-worker-e2e",
    )
    assert goal.workflow_id is not None
    workflow_id = goal.workflow_id
    workflow = workflows.get_workflow(workflow_id)
    assert workflow.status is WorkflowStatus.RUNNING
    assert workflow.steps[0].task_id is not None

    synthesis = GoalSynthesisCoordinator(
        goals=goals,
        workflows=workflows,
        result_records=result_records,
        result_store=result_store,
        local=DeterministicLocal(),
    )
    handoff = GoalHandoffCoordinator(
        paths=paths,
        goals=goals,
        workflows=workflows,
        result_records=result_records,
        result_store=result_store,
    )
    runtime = WorkerRuntime(
        queue=queue,
        state_store=WorkerStateStore(
            paths.state_dir / "goal-e2e-worker-status.json",
            stale_after_seconds=30,
        ),
        worker_id="goal-e2e-worker",
        handlers={
            "autonomous.discovery.v1": _discovery_handler,
            "autonomous.goal_synthesis.v1": synthesis.handler,
            "autonomous.goal_handoff.v1": handoff.handler,
        },
        database=database,
        result_store=result_store,
        lease_seconds=30,
        heartbeat_seconds=2,
        poll_seconds=0.01,
    )

    for expected_task_type in (
        "autonomous.discovery.v1",
        "autonomous.goal_synthesis.v1",
        "autonomous.goal_handoff.v1",
    ):
        cycle = runtime.run_once()
        assert cycle.processed is True
        assert cycle.succeeded is True
        assert cycle.task_id is not None
        assert queue.get(cycle.task_id).task_type == expected_task_type
        workflows.reconcile(workflow_id)

    completed_workflow = workflows.get_workflow(workflow_id)
    assert completed_workflow.status is WorkflowStatus.COMPLETED
    assert all(step.task_id for step in completed_workflow.steps)
    assert goal_service.get(goal.goal_id).status is GoalStatus.COMPLETED

    access = GoalHandoffAccess(
        paths=paths,
        goals=goals,
        workflows=workflows,
        result_records=result_records,
        result_store=result_store,
    )
    metadata = access.metadata(goal.goal_id)
    assert metadata.handoff_ready is True
    assert metadata.manual_web_gpt_upload_required is True
    assert metadata.goal_id == goal.goal_id
    assert "/" not in metadata.package_name
    assert "\\" not in metadata.package_name

    package = access.verified_package(goal.goal_id)
    assert package.parent == paths.autonomous_handoffs_dir
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        assert "WEB_GPT_MASTER_PROMPT.txt" in names
        assert "HANDOFF_MANIFEST.json" in names
        evidence_markdown = archive.read("04_EVIDENCE.md").decode("utf-8")
        assert "消费者关注尺寸是否适合大型犬" in evidence_markdown
        assert _CONNECTED_TEXT in evidence_markdown
        assert "legacy41-e2e-1" in evidence_markdown

    prompt = access.fixed_prompt(goal.goal_id)
    # Match the versioned production prompt's real fact-discipline contract instead of
    # requiring one arbitrary synonym such as “禁止杜撰”.
    assert "不要伪造来源、评论" in prompt
    assert "所有事实性结论必须能够回溯到交接包中的 evidence_id / source_id" in prompt
    assert "AI 视频" in prompt
    database.close()
