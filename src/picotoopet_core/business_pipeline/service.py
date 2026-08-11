"""Restart-safe orchestration across Business, Creative, and Production stages."""

from __future__ import annotations

from uuid import uuid4

from picotoopet_core.business.models import (
    BusinessAnalysisProfile,
    BusinessQualityOutcome,
    BusinessWorkPackageStatus,
)
from picotoopet_core.creative.models import CreativeJobCreateRequest, CreativeJobStatus
from picotoopet_core.production.models import ProductionJobCreateRequest, ProductionJobStatus

from .models import (
    BusinessAdapterProfile,
    BusinessPipelineQualityOutcome,
    BusinessPipelineRunRecord,
    BusinessPipelineStatus,
)
from .repository import BusinessPipelineRepository

_ADAPTER_ANALYSIS_PROFILE = {
    BusinessAdapterProfile.AMAZON_REVIEWS_EXPORT_V1: BusinessAnalysisProfile.REVIEWS_VOICE_OF_CUSTOMER_V1,
    BusinessAdapterProfile.INSPIRATION_IDEAS_EXPORT_V1: BusinessAnalysisProfile.IDEAS_PATTERN_ANALYSIS_V1,
}

_BUSINESS_TERMINAL = {
    BusinessWorkPackageStatus.NEEDS_DEEP_AI: (
        BusinessPipelineStatus.NEEDS_DEEP_AI,
        BusinessPipelineQualityOutcome.NEEDS_DEEP_AI,
    ),
    BusinessWorkPackageStatus.NEEDS_HUMAN: (
        BusinessPipelineStatus.NEEDS_HUMAN,
        BusinessPipelineQualityOutcome.NEEDS_HUMAN,
    ),
    BusinessWorkPackageStatus.REJECTED: (
        BusinessPipelineStatus.REJECTED,
        BusinessPipelineQualityOutcome.REJECT,
    ),
    BusinessWorkPackageStatus.FAILED: (
        BusinessPipelineStatus.FAILED,
        BusinessPipelineQualityOutcome.FAILED,
    ),
    BusinessWorkPackageStatus.CANCELLED: (
        BusinessPipelineStatus.CANCELLED,
        BusinessPipelineQualityOutcome.CANCELLED,
    ),
}

_CREATIVE_TERMINAL = {
    CreativeJobStatus.NEEDS_DEEP_AI: (
        BusinessPipelineStatus.NEEDS_DEEP_AI,
        BusinessPipelineQualityOutcome.NEEDS_DEEP_AI,
    ),
    CreativeJobStatus.NEEDS_HUMAN: (
        BusinessPipelineStatus.NEEDS_HUMAN,
        BusinessPipelineQualityOutcome.NEEDS_HUMAN,
    ),
    CreativeJobStatus.REJECTED: (
        BusinessPipelineStatus.REJECTED,
        BusinessPipelineQualityOutcome.REJECT,
    ),
    CreativeJobStatus.FAILED: (
        BusinessPipelineStatus.FAILED,
        BusinessPipelineQualityOutcome.FAILED,
    ),
    CreativeJobStatus.CANCELLED: (
        BusinessPipelineStatus.CANCELLED,
        BusinessPipelineQualityOutcome.CANCELLED,
    ),
}

_PRODUCTION_TERMINAL = {
    ProductionJobStatus.NEEDS_HUMAN: (
        BusinessPipelineStatus.NEEDS_HUMAN,
        BusinessPipelineQualityOutcome.NEEDS_HUMAN,
    ),
    ProductionJobStatus.FAILED: (
        BusinessPipelineStatus.FAILED,
        BusinessPipelineQualityOutcome.FAILED,
    ),
    ProductionJobStatus.CANCELLED: (
        BusinessPipelineStatus.CANCELLED,
        BusinessPipelineQualityOutcome.CANCELLED,
    ),
}


class BusinessPipelineService:
    """Coordinate durable child stages without duplicating their business logic."""

    def __init__(
        self,
        *,
        repository: BusinessPipelineRepository,
        business: object,
        creative: object,
        production: object,
    ) -> None:
        self.repository = repository
        self.business = business
        self.creative = creative
        self.production = production

    def create_run(
        self,
        *,
        work_package_id: str,
        adapter_profile: BusinessAdapterProfile,
        idempotency_key: str,
    ) -> BusinessPipelineRunRecord:
        work = self.business.get_work_package(work_package_id)  # type: ignore[attr-defined]
        expected_profile = _ADAPTER_ANALYSIS_PROFILE[adapter_profile]
        work_profile = getattr(work, "analysis_profile", None)
        if work_profile is not None and work_profile != expected_profile:
            raise ValueError("PIPELINE_ADAPTER_PROFILE_MISMATCH")
        return self.repository.create_run(
            pipeline_run_id=str(uuid4()),
            work_package_id=work.work_package_id,
            project_key=work.project_key,
            producer_id=work.producer_id,
            producer_version=work.producer_version,
            adapter_profile=adapter_profile,
            idempotency_key=idempotency_key,
        )

    def get_run(self, pipeline_run_id: str) -> BusinessPipelineRunRecord:
        return self.repository.get_run(pipeline_run_id)

    def list_runs(self, *, limit: int = 100) -> list[BusinessPipelineRunRecord]:
        return self.repository.list_runs(limit=limit)

    def _terminal(
        self,
        run: BusinessPipelineRunRecord,
        status: BusinessPipelineStatus,
        outcome: BusinessPipelineQualityOutcome,
        source: object,
    ) -> BusinessPipelineRunRecord:
        return self.repository.transition(
            run.pipeline_run_id,
            status,
            quality_outcome=outcome,
            failure_code=getattr(source, "failure_code", None),
            error_message=getattr(source, "error_message", None),
            finished=True,
        )

    def reconcile(self, pipeline_run_id: str) -> BusinessPipelineRunRecord:
        run = self.repository.get_run(pipeline_run_id)
        if run.status in {
            BusinessPipelineStatus.COMPLETED,
            BusinessPipelineStatus.NEEDS_DEEP_AI,
            BusinessPipelineStatus.NEEDS_HUMAN,
            BusinessPipelineStatus.REJECTED,
            BusinessPipelineStatus.FAILED,
            BusinessPipelineStatus.CANCELLED,
        }:
            return run

        work = self.business.get_work_package(run.work_package_id)  # type: ignore[attr-defined]
        if work.status in _BUSINESS_TERMINAL:
            status, outcome = _BUSINESS_TERMINAL[work.status]
            return self._terminal(run, status, outcome, work)
        if work.status is not BusinessWorkPackageStatus.COMPLETED:
            return self.repository.transition(run.pipeline_run_id, BusinessPipelineStatus.BUSINESS_ANALYSIS)

        result = self.business.result_for(run.work_package_id)  # type: ignore[attr-defined]
        if result is None:
            return self.repository.transition(run.pipeline_run_id, BusinessPipelineStatus.BUSINESS_ANALYSIS)
        if result.quality_outcome is not BusinessQualityOutcome.PASS:
            result_mapping = {
                BusinessQualityOutcome.NEEDS_DEEP_AI: (
                    BusinessPipelineStatus.NEEDS_DEEP_AI,
                    BusinessPipelineQualityOutcome.NEEDS_DEEP_AI,
                ),
                BusinessQualityOutcome.NEEDS_HUMAN: (
                    BusinessPipelineStatus.NEEDS_HUMAN,
                    BusinessPipelineQualityOutcome.NEEDS_HUMAN,
                ),
                BusinessQualityOutcome.REJECT: (
                    BusinessPipelineStatus.REJECTED,
                    BusinessPipelineQualityOutcome.REJECT,
                ),
            }
            mapped = result_mapping.get(result.quality_outcome)
            if mapped is None:
                return self._terminal(
                    run,
                    BusinessPipelineStatus.FAILED,
                    BusinessPipelineQualityOutcome.FAILED,
                    result,
                )
            return self._terminal(run, mapped[0], mapped[1], result)

        run = self.repository.bind_child_once(
            run.pipeline_run_id,
            "result_package_id",
            result.result_package_id,
        )
        if run.creative_job_id is None:
            creative_job = self.creative.create_job(  # type: ignore[attr-defined]
                CreativeJobCreateRequest(
                    source_result_package_ids=[result.result_package_id],
                    creative_profile="creative.content_plan.v1",
                    creative_objective=None,
                    idempotency_key=f"pipeline:{run.pipeline_run_id}:creative",
                )
            )
            run = self.repository.bind_child_once(
                run.pipeline_run_id,
                "creative_job_id",
                creative_job.creative_job_id,
            )

        creative_job = self.creative.get_job(run.creative_job_id)  # type: ignore[attr-defined]
        if creative_job.status in _CREATIVE_TERMINAL:
            status, outcome = _CREATIVE_TERMINAL[creative_job.status]
            return self._terminal(run, status, outcome, creative_job)
        if creative_job.status is not CreativeJobStatus.CREATIVE_READY:
            return self.repository.transition(run.pipeline_run_id, BusinessPipelineStatus.CREATIVE_INTELLIGENCE)

        creative_package = self.creative.get_package(run.creative_job_id)  # type: ignore[attr-defined]
        if creative_package is None:
            return self.repository.transition(run.pipeline_run_id, BusinessPipelineStatus.CREATIVE_INTELLIGENCE)
        run = self.repository.bind_child_once(
            run.pipeline_run_id,
            "creative_package_id",
            creative_package.creative_package_id,
        )

        if run.production_job_id is None:
            production_job = self.production.create_job(  # type: ignore[attr-defined]
                ProductionJobCreateRequest(
                    creative_package_id=creative_package.creative_package_id,
                    production_profile="production.comfyui.v1",
                    idempotency_key=f"pipeline:{run.pipeline_run_id}:production",
                )
            )
            run = self.repository.bind_child_once(
                run.pipeline_run_id,
                "production_job_id",
                production_job.production_job_id,
            )

        production_job = self.production.get_job(run.production_job_id)  # type: ignore[attr-defined]
        if production_job.status in _PRODUCTION_TERMINAL:
            status, outcome = _PRODUCTION_TERMINAL[production_job.status]
            return self._terminal(run, status, outcome, production_job)
        if production_job.status is ProductionJobStatus.PRODUCTION_READY:
            production_package = self.production.get_package(run.production_job_id)  # type: ignore[attr-defined]
            if production_package is None:
                return self.repository.transition(run.pipeline_run_id, BusinessPipelineStatus.QUALITY_CHECK)
            run = self.repository.bind_child_once(
                run.pipeline_run_id,
                "production_package_id",
                production_package.production_package_id,
            )
            # Task 3 owns immutable Return Package creation and final Completed transition.
            return self.repository.transition(run.pipeline_run_id, BusinessPipelineStatus.QUALITY_CHECK)
        if production_job.status in {
            ProductionJobStatus.CLAIMED,
            ProductionJobStatus.PREFLIGHT,
            ProductionJobStatus.RENDERING,
            ProductionJobStatus.COLLECTING,
            ProductionJobStatus.QUALITY_CHECK,
        }:
            return self.repository.transition(run.pipeline_run_id, BusinessPipelineStatus.RENDERING)
        return self.repository.transition(run.pipeline_run_id, BusinessPipelineStatus.AWAITING_GPU)

    def cancel(self, pipeline_run_id: str) -> BusinessPipelineRunRecord:
        run = self.repository.get_run(pipeline_run_id)
        if run.status in {
            BusinessPipelineStatus.COMPLETED,
            BusinessPipelineStatus.NEEDS_DEEP_AI,
            BusinessPipelineStatus.NEEDS_HUMAN,
            BusinessPipelineStatus.REJECTED,
            BusinessPipelineStatus.FAILED,
            BusinessPipelineStatus.CANCELLED,
        }:
            return run
        if run.production_job_id is not None and hasattr(self.production, "cancel"):
            self.production.cancel(run.production_job_id)  # type: ignore[attr-defined]
        return self.repository.transition(
            pipeline_run_id,
            BusinessPipelineStatus.CANCELLED,
            quality_outcome=BusinessPipelineQualityOutcome.CANCELLED,
            finished=True,
        )
