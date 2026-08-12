from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from picotoopet_core.business.models import (
    BusinessQualityOutcome,
    BusinessWorkPackageStatus,
    DeepAiHandoffRecord,
    WorkPackageManifest,
)
from picotoopet_core.business.repository import BusinessRepository
from picotoopet_core.business.store import BusinessArtifactStore
from picotoopet_core.business_pipeline.models import (
    BusinessAdapterProfile,
    BusinessPipelineStatus,
)
from picotoopet_core.business_pipeline.repository import BusinessPipelineRepository
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.creative.models import (
    CreativeDeepAiHandoffRecord,
    CreativeJobStatus,
    CreativeProfile,
    CreativeQualityOutcome,
    CreativeStageKind,
)
from picotoopet_core.creative.repository import CreativeRepository
from picotoopet_core.db.database import Database
from picotoopet_core.deep_ai.models import DeepAiEscalationStatus
from picotoopet_core.deep_ai.repository import DeepAiRepository
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def _work(business: BusinessRepository):  # type: ignore[no-untyped-def]
    work_id = str(uuid4())
    manifest = WorkPackageManifest.model_validate(
        {
            "schema_version": "1.0",
            "package_id": work_id,
            "idempotency_key": f"work:{work_id}",
            "producer_id": "amazon-research-app",
            "producer_version": "1.0.0",
            "created_at": "2026-08-11T12:00:00Z",
            "project_key": "pet-dryer-us",
            "analysis_profile": "reviews.voice_of_customer.v1",
            "objective": "Find supported customer insights.",
            "inputs": [
                {
                    "artifact_id": "reviews",
                    "path": "inputs/reviews.jsonl",
                    "media_type": "application/x-ndjson",
                    "sha256": "a" * 64,
                    "size_bytes": 128,
                    "record_key_field": "review_id",
                }
            ],
        }
    )
    work = business.create_or_get_work_package(
        manifest,
        source_digest="b" * 64,
        compressed_size_bytes=256,
    )
    handoff_id = str(uuid4())
    handoff = DeepAiHandoffRecord(
        handoff_id=handoff_id,
        work_package_id=work_id,
        source_digest="b" * 64,
        preprocess_digest="c" * 64,
        local_result_digest="d" * 64,
        quality_reasons=["semantic uncertainty"],
        return_schema={
            "type": "object",
            "required": ["findings"],
            "properties": {"findings": {"type": "array"}},
        },
        package_digest="e" * 64,
        package_relpath=f"runtime/business/handoffs/{handoff_id}.zip",
        status="Prepared",
    )
    business.save_handoff(handoff)
    business.transition_work_package(
        work_id,
        BusinessWorkPackageStatus.NEEDS_DEEP_AI,
        preprocess_digest="c" * 64,
        deep_ai_handoff_id=handoff_id,
        finished=True,
    )
    return business.get_work_package(work_id), handoff


def _deep_job(
    deep: DeepAiRepository,
    *,
    source_kind: str,
    source_id: str,
    source_digest: str,
):  # type: ignore[no-untyped-def]
    job = deep.prepare_job(
        escalation_job_id=str(uuid4()),
        source_kind=source_kind,
        source_id=source_id,
        source_digest=source_digest,
        policy_version="deep-ai.escalation.v1",
        sanitized_package_relpath="runtime/deep-ai/requests/request.json",
        sanitized_package_digest="1" * 64,
        sanitizer_version="deep-ai.sanitizer.v1",
        provider_profile_id="paid.reasoning.v1",
        provider_profile_digest="2" * 64,
        model_id="gpt-5.6-terra",
        max_input_tokens=12000,
        max_output_tokens=4000,
        max_calls=2,
        max_cost_usd="0.50",
    )
    return deep.set_job_status(job.escalation_job_id, DeepAiEscalationStatus.VALIDATING)


def test_business_pass_result_becomes_normal_pass_package_and_reopens_pipeline(tmp_path: Path) -> None:
    from picotoopet_core.deep_ai.continuation import DeepAiSourceContinuation

    database = _database(tmp_path)
    try:
        paths = RuntimePaths.from_root(tmp_path / "runtime")
        paths.ensure()
        business = BusinessRepository(database)
        creative = CreativeRepository(database)
        pipelines = BusinessPipelineRepository(database)
        queue = DiagnosticQueueRepository(database)
        deep = DeepAiRepository(database)
        work, _ = _work(business)
        run = pipelines.create_run(
            pipeline_run_id=str(uuid4()),
            work_package_id=work.work_package_id,
            project_key=work.project_key,
            producer_id=work.producer_id,
            producer_version=work.producer_version,
            adapter_profile=BusinessAdapterProfile.AMAZON_REVIEWS_EXPORT_V1,
            idempotency_key=f"pipeline:{work.work_package_id}",
        )
        pipelines.transition(run.pipeline_run_id, BusinessPipelineStatus.NEEDS_DEEP_AI, finished=True)
        job = _deep_job(
            deep,
            source_kind="business.local_intelligence",
            source_id=work.work_package_id,
            source_digest="b" * 64,
        )
        continuation = DeepAiSourceContinuation(
            business_repository=business,
            business_store=BusinessArtifactStore(paths),
            creative_repository=creative,
            queue=queue,
            pipeline_repository=pipelines,
        )
        output = {"findings": [{"summary": "Supported insight"}]}
        result_ref = continuation.apply_pass(
            job=job,
            output=output,
            output_digest="4" * 64,
        )

        updated_work = business.get_work_package(work.work_package_id)
        result = business.result_for(work.work_package_id)
        assert updated_work.status is BusinessWorkPackageStatus.COMPLETED
        assert result is not None
        assert result.quality_outcome is BusinessQualityOutcome.PASS
        assert result.result == output
        assert result.result_digest == "4" * 64
        assert result_ref == result.result_package_id
        assert pipelines.get_run(run.pipeline_run_id).status is BusinessPipelineStatus.BUSINESS_ANALYSIS
    finally:
        database.close()


def test_creative_pass_completes_failed_stage_enqueues_resume_and_reopens_pipeline(tmp_path: Path) -> None:
    from picotoopet_core.deep_ai.continuation import DeepAiSourceContinuation

    database = _database(tmp_path)
    try:
        paths = RuntimePaths.from_root(tmp_path / "runtime")
        paths.ensure()
        business = BusinessRepository(database)
        creative = CreativeRepository(database)
        pipelines = BusinessPipelineRepository(database)
        queue = DiagnosticQueueRepository(database)
        deep = DeepAiRepository(database)
        work, _ = _work(business)
        creative_id = str(uuid4())
        creative.create_job(
            creative_job_id=creative_id,
            project_key=work.project_key,
            creative_profile=CreativeProfile.CONTENT_PLAN_V1,
            creative_objective=None,
            objective_digest="5" * 64,
            source_set_digest="6" * 64,
            idempotency_key=f"creative:{creative_id}",
        )
        stage = creative.create_or_get_stage(
            creative_job_id=creative_id,
            stage_kind=CreativeStageKind.IDEA_RANKING,
            input_digest="7" * 64,
            template_version="creative.idea-ranking.v1",
        )
        creative.update_stage(
            stage.stage_run_id,
            status="NeedsDeepAI",
            model_attempts=2,
            result={"draft": "uncertain"},
            result_digest="8" * 64,
            quality_outcome=CreativeQualityOutcome.NEEDS_DEEP_AI,
            finished=True,
        )
        handoff_id = str(uuid4())
        creative.save_handoff(
            CreativeDeepAiHandoffRecord(
                handoff_id=handoff_id,
                creative_job_id=creative_id,
                stage_kind=CreativeStageKind.IDEA_RANKING,
                source_set_digest="6" * 64,
                failed_result_digest="8" * 64,
                quality_reasons=["semantic uncertainty"],
                return_schema={"type": "object", "required": ["ranked_ideas"]},
                package_digest="9" * 64,
                package_relpath=f"runtime/creative/handoffs/{handoff_id}.zip",
                status="Prepared",
                created_at=datetime.now(UTC),
            )
        )
        creative.transition_job(
            creative_id,
            CreativeJobStatus.NEEDS_DEEP_AI,
            current_stage=CreativeStageKind.IDEA_RANKING,
            deep_ai_handoff_id=handoff_id,
            finished=True,
        )
        run = pipelines.create_run(
            pipeline_run_id=str(uuid4()),
            work_package_id=work.work_package_id,
            project_key=work.project_key,
            producer_id=work.producer_id,
            producer_version=work.producer_version,
            adapter_profile=BusinessAdapterProfile.AMAZON_REVIEWS_EXPORT_V1,
            idempotency_key=f"pipeline:{work.work_package_id}",
        )
        pipelines.bind_child_once(run.pipeline_run_id, "creative_job_id", creative_id)
        pipelines.transition(run.pipeline_run_id, BusinessPipelineStatus.NEEDS_DEEP_AI, finished=True)
        job = _deep_job(
            deep,
            source_kind="creative.intelligence",
            source_id=creative_id,
            source_digest="6" * 64,
        )
        continuation = DeepAiSourceContinuation(
            business_repository=business,
            business_store=BusinessArtifactStore(paths),
            creative_repository=creative,
            queue=queue,
            pipeline_repository=pipelines,
        )
        output = {"ranked_ideas": [{"title": "Evidence-led dryer education"}]}
        result_ref = continuation.apply_pass(job=job, output=output, output_digest="a" * 64)

        resumed_stage = creative.get_stage(creative_id, CreativeStageKind.IDEA_RANKING)
        resumed_job = creative.get_job(creative_id)
        assert resumed_stage is not None
        assert resumed_stage.status == "Completed"
        assert resumed_stage.quality_outcome is CreativeQualityOutcome.PASS
        assert resumed_stage.result == output
        assert resumed_job.status is CreativeJobStatus.IDEA_RANKING
        assert resumed_job.finished_at is None
        assert creative.handoff_for(creative_id) is None
        historical_handoff = creative.handoff_history_for(creative_id)
        assert historical_handoff is not None
        assert historical_handoff.status == "Resolved"
        assert result_ref == resumed_stage.stage_run_id
        tasks = [item for item in queue.list(limit=100) if item.resource_tag == f"creative:{creative_id}"]
        assert len(tasks) == 1
        queued_idempotency = database.scalar(
            "SELECT idempotency_key FROM tasks WHERE task_id=?",
            (tasks[0].task_id,),
        )
        assert queued_idempotency == f"creative:{creative_id}:deep-ai-resume:{'a' * 64}"
        assert pipelines.get_run(run.pipeline_run_id).status is BusinessPipelineStatus.CREATIVE_INTELLIGENCE
    finally:
        database.close()


def test_creative_repository_keeps_resolved_handoff_as_history_only() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "picotoopet_core"
        / "creative"
        / "repository.py"
    ).read_text(encoding="utf-8")
    assert "resolve_handoff" in source
    assert "handoff_history_for" in source
    assert "status!='Resolved'" in source
