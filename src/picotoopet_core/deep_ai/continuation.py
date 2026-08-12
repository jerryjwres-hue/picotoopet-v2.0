"""Restart-safe continuation of source stages after a validated Deep-AI PASS."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from picotoopet_core.business.models import (
    BusinessQualityOutcome,
    BusinessResultPackageRecord,
    BusinessWorkPackageStatus,
)
from picotoopet_core.business.repository import BusinessRepository
from picotoopet_core.business.store import BusinessArtifactStore
from picotoopet_core.business_pipeline.models import BusinessPipelineStatus
from picotoopet_core.business_pipeline.repository import BusinessPipelineRepository
from picotoopet_core.creative.models import (
    CreativeJobStatus,
    CreativeQualityOutcome,
    CreativeStageKind,
)
from picotoopet_core.creative.repository import CreativeRepository
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository

from .models import DeepAiEscalationRecord


_STAGE_JOB_STATUS = {
    CreativeStageKind.IDEA_RANKING: CreativeJobStatus.IDEA_RANKING,
    CreativeStageKind.CREATIVE_BRIEF: CreativeJobStatus.BRIEF_GENERATION,
    CreativeStageKind.SCRIPT: CreativeJobStatus.SCRIPT_GENERATION,
    CreativeStageKind.SHOT_PLAN: CreativeJobStatus.SHOT_PLANNING,
}


class DeepAiSourceContinuation:
    """Apply only a validated PASS and reopen the existing deterministic pipeline seam."""

    def __init__(
        self,
        *,
        business_repository: BusinessRepository,
        business_store: BusinessArtifactStore,
        creative_repository: CreativeRepository,
        queue: DiagnosticQueueRepository,
        pipeline_repository: BusinessPipelineRepository,
    ) -> None:
        self.business_repository = business_repository
        self.business_store = business_store
        self.creative_repository = creative_repository
        self.queue = queue
        self.pipeline_repository = pipeline_repository

    def apply_pass(
        self,
        *,
        job: DeepAiEscalationRecord,
        output: dict[str, object],
        output_digest: str,
    ) -> str:
        if job.source_kind == "business.local_intelligence":
            return self._resume_business(job, output, output_digest)
        if job.source_kind == "creative.intelligence":
            return self._resume_creative(job, output, output_digest)
        raise ValueError("DEEP_AI_SOURCE_NOT_ELIGIBLE")

    def _resume_business(
        self,
        job: DeepAiEscalationRecord,
        output: dict[str, object],
        output_digest: str,
    ) -> str:
        work = self.business_repository.get_work_package(job.source_id)
        existing = self.business_repository.result_for(work.work_package_id)
        if existing is not None:
            if existing.result_digest != output_digest:
                raise ValueError("DEEP_AI_SOURCE_RESULT_IMMUTABLE")
            self._reopen_pipeline_for_business(
                work.work_package_id,
                existing.result_package_id,
            )
            return existing.result_package_id
        if work.status is not BusinessWorkPackageStatus.NEEDS_DEEP_AI:
            raise ValueError("DEEP_AI_BUSINESS_SOURCE_NOT_WAITING")
        handoff = self.business_repository.handoff_for(work.work_package_id)
        if handoff is None or handoff.source_digest != job.source_digest:
            raise ValueError("DEEP_AI_BUSINESS_SOURCE_IDENTITY_MISMATCH")

        result_package_id = str(
            uuid5(
                NAMESPACE_URL,
                f"picotoopet:deep-ai:business:{job.escalation_job_id}:{output_digest}",
            )
        )
        payload: dict[str, object] = {
            "schema_version": "1.0",
            "result_package_id": result_package_id,
            "work_package_id": work.work_package_id,
            "analysis_profile": work.analysis_profile.value,
            "source_digest": handoff.source_digest,
            "preprocess_digest": handoff.preprocess_digest,
            "model_adapter_version": "deep-ai.provider.v1",
            "configured_model_id": job.model_id,
            "template_version": "deep-ai.reasoning.v1",
            "quality_outcome": BusinessQualityOutcome.PASS.value,
            "result_digest": output_digest,
            "result": output,
            "warnings": ["resolved_by_deep_ai"],
            "provenance": {
                "escalation_job_id": job.escalation_job_id,
                "sanitized_package_digest": job.sanitized_package_digest,
                "provider_profile_id": job.provider_profile_id,
                "provider_profile_digest": job.provider_profile_digest,
            },
        }
        package_relpath, _package_digest = self.business_store.write_result_package(
            result_package_id=result_package_id,
            payload=payload,
        )
        record = BusinessResultPackageRecord(
            result_package_id=result_package_id,
            work_package_id=work.work_package_id,
            analysis_profile=work.analysis_profile,
            source_digest=handoff.source_digest,
            preprocess_digest=handoff.preprocess_digest,
            model_adapter_version="deep-ai.provider.v1",
            configured_model_id=job.model_id,
            template_version="deep-ai.reasoning.v1",
            quality_outcome=BusinessQualityOutcome.PASS,
            result_digest=output_digest,
            package_relpath=package_relpath,
            result=output,
            warnings=["resolved_by_deep_ai"],
            created_at=datetime.now(UTC),
        )
        saved = self.business_repository.save_result(record)
        self.business_repository.transition_work_package(
            work.work_package_id,
            BusinessWorkPackageStatus.COMPLETED,
            preprocess_digest=handoff.preprocess_digest,
            result_package_id=saved.result_package_id,
            finished=True,
        )
        self._reopen_pipeline_for_business(work.work_package_id, saved.result_package_id)
        return saved.result_package_id

    def _reopen_pipeline_for_business(
        self,
        work_package_id: str,
        result_package_id: str,
    ) -> None:
        for run in self.pipeline_repository.list_runs(limit=500):
            if run.work_package_id != work_package_id:
                continue
            if run.result_package_id is None:
                self.pipeline_repository.bind_child_once(
                    run.pipeline_run_id,
                    "result_package_id",
                    result_package_id,
                )
            if run.status is BusinessPipelineStatus.NEEDS_DEEP_AI:
                self.pipeline_repository.transition(
                    run.pipeline_run_id,
                    BusinessPipelineStatus.BUSINESS_ANALYSIS,
                )

    def _resume_creative(
        self,
        job: DeepAiEscalationRecord,
        output: dict[str, object],
        output_digest: str,
    ) -> str:
        creative = self.creative_repository.get_job(job.source_id)
        handoff = self.creative_repository.handoff_history_for(creative.creative_job_id)
        if handoff is None or handoff.source_set_digest != job.source_digest:
            raise ValueError("DEEP_AI_CREATIVE_SOURCE_IDENTITY_MISMATCH")
        stage = self.creative_repository.get_stage(
            creative.creative_job_id,
            handoff.stage_kind,
        )
        if stage is None:
            raise ValueError("DEEP_AI_CREATIVE_STAGE_MISSING")
        if stage.status == "Completed" and stage.quality_outcome is CreativeQualityOutcome.PASS:
            if stage.result_digest != output_digest:
                raise ValueError("DEEP_AI_SOURCE_RESULT_IMMUTABLE")
        else:
            self.creative_repository.update_stage(
                stage.stage_run_id,
                status="Completed",
                model_attempts=stage.model_attempts,
                result=output,
                result_digest=output_digest,
                quality_outcome=CreativeQualityOutcome.PASS,
                finished=True,
            )
        self.creative_repository.resolve_handoff(creative.creative_job_id)
        resume_status = _STAGE_JOB_STATUS[handoff.stage_kind]
        now = datetime.now(UTC).isoformat()
        self.creative_repository.database.execute(
            "UPDATE creative_jobs SET status=?,current_stage=?,failure_code=NULL,error_message=NULL,"
            "updated_at=?,finished_at=NULL WHERE creative_job_id=?",
            (
                resume_status.value,
                handoff.stage_kind.value,
                now,
                creative.creative_job_id,
            ),
        )
        self.queue.create(
            TaskCreate(
                project_id=None,
                task_type="creative.content_plan.v1",
                payload={
                    "creative_job_id": creative.creative_job_id,
                    "source_set_digest": creative.source_set_digest,
                    "creative_profile": creative.creative_profile.value,
                },
                priority=100,
                resource_tag=f"creative:{creative.creative_job_id}",
                idempotency_key=(
                    f"creative:{creative.creative_job_id}:deep-ai-resume:{output_digest}"
                ),
                max_attempts=2,
                timeout_seconds=3600,
            )
        )
        for run in self.pipeline_repository.list_runs(limit=500):
            if run.creative_job_id != creative.creative_job_id:
                continue
            if run.status is BusinessPipelineStatus.NEEDS_DEEP_AI:
                self.pipeline_repository.transition(
                    run.pipeline_run_id,
                    BusinessPipelineStatus.CREATIVE_INTELLIGENCE,
                )
        return stage.stage_run_id
