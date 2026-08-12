"""Authenticated, bounded Deep-AI escalation, learning, evaluation, and shadow routes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.api.errors import ApiError
from picotoopet_core.deep_ai.evaluation import (
    QualityEvaluationMetric,
    QualityEvaluationRun,
    QualityEvaluationScope,
    QualityEvaluationSnapshot,
    QualityImprovementCandidate,
    QualityImprovementCandidateReview,
)
from picotoopet_core.deep_ai.learning import DeepAiLearningLedger, DeepAiLearningObservation
from picotoopet_core.deep_ai.models import (
    DeepAiEscalationRecord,
    DeepAiHumanAction,
    DeepAiLearningEvent,
)
from picotoopet_core.deep_ai.service import DeepAiReadiness
from picotoopet_core.deep_ai.shadow import (
    QualityShadowArmMetric,
    QualityShadowReview,
    QualityShadowRun,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


class DeepAiEscalationPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=160)


class DeepAiReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeepAiUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    escalation_job_id: str
    calls_used: int = Field(ge=0, le=2)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: Decimal = Field(ge=Decimal("0"))


class DeepAiFeedbackAction(StrEnum):
    ACCEPTED = "Accepted"
    REJECTED = "Rejected"
    MODIFIED = "Modified"


class DeepAiFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: DeepAiFeedbackAction
    reason_tags: list[str] = Field(default_factory=list, max_length=20)
    final_content_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    downstream_ref: str | None = Field(default=None, max_length=256)
    idempotency_key: str = Field(min_length=1, max_length=256)


class QualityEvaluationSnapshotRequest(BaseModel):
    """Closed snapshot scope; user input cannot provide policy, execution, SQL, or formulas."""

    model_config = ConfigDict(extra="forbid")

    project_key: str = Field(min_length=1, max_length=200)
    evaluation_profile_id: Literal["quality.offline.v1"] = "quality.offline.v1"
    stage_profile: str | None = Field(default=None, min_length=1, max_length=200)
    start_at: datetime | None = None
    end_at: datetime | None = None
    limit: int = Field(default=10000, ge=1, le=10000)


class QualityEvaluationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(min_length=1, max_length=160)


class QualityEvaluationReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QualityImprovementReviewAction(StrEnum):
    REVIEWED = "Reviewed"
    ACCEPTED_FOR_SHADOW = "AcceptedForShadow"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"


class QualityImprovementReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: QualityImprovementReviewAction
    idempotency_key: str = Field(min_length=1, max_length=256)


class QualityShadowRunRequest(BaseModel):
    """Closed Shadow request; only the already-reviewed candidate identity is caller supplied."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=160)


class QualityShadowReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QualityShadowReviewAction(StrEnum):
    REVIEWED = "Reviewed"
    ACCEPTED_FOR_PROMOTION_REVIEW = "AcceptedForPromotionReview"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"


class QualityShadowReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: QualityShadowReviewAction
    idempotency_key: str = Field(min_length=1, max_length=256)


@router.post(
    "/deep-ai/escalations",
    response_model=DeepAiEscalationRecord,
    status_code=status.HTTP_201_CREATED,
)
def prepare_deep_ai_escalation(
    payload: DeepAiEscalationPrepareRequest,
    request: Request,
) -> DeepAiEscalationRecord:
    return execute_deep_ai(
        lambda: request.app.state.services.deep_ai.prepare_from_source(
            source_kind=payload.source_kind,
            source_id=payload.source_id,
            requested_by="api",
        )
    )


@router.get("/deep-ai/escalations", response_model=list[DeepAiEscalationRecord])
def list_deep_ai_escalations(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[DeepAiEscalationRecord]:
    return request.app.state.services.deep_ai_repository.list_jobs(limit=limit)


@router.get(
    "/deep-ai/escalations/{escalation_job_id}",
    response_model=DeepAiEscalationRecord,
)
def get_deep_ai_escalation(
    escalation_job_id: str,
    request: Request,
) -> DeepAiEscalationRecord:
    return execute_deep_ai(
        lambda: request.app.state.services.deep_ai_repository.get_job(escalation_job_id)
    )


@router.post(
    "/deep-ai/escalations/{escalation_job_id}/reconcile",
    response_model=DeepAiEscalationRecord,
)
def reconcile_deep_ai_escalation(
    escalation_job_id: str,
    payload: DeepAiReconcileRequest,
    request: Request,
) -> DeepAiEscalationRecord:
    del payload
    return execute_deep_ai(
        lambda: request.app.state.services.deep_ai.reconcile(escalation_job_id)
    )


@router.get(
    "/deep-ai/escalations/{escalation_job_id}/readiness",
    response_model=DeepAiReadiness,
)
def get_deep_ai_readiness(
    escalation_job_id: str,
    request: Request,
) -> DeepAiReadiness:
    return execute_deep_ai(
        lambda: request.app.state.services.deep_ai.readiness(escalation_job_id)
    )


@router.get(
    "/deep-ai/escalations/{escalation_job_id}/usage",
    response_model=DeepAiUsage,
)
def get_deep_ai_usage(
    escalation_job_id: str,
    request: Request,
) -> DeepAiUsage:
    def operation() -> DeepAiUsage:
        repository = request.app.state.services.deep_ai_repository
        repository.get_job(escalation_job_id)
        attempts = repository.list_attempts(escalation_job_id)
        completed = [item for item in attempts if item.actual_cost_usd is not None]
        return DeepAiUsage(
            escalation_job_id=escalation_job_id,
            calls_used=len(completed),
            input_tokens=sum(item.input_tokens or 0 for item in completed),
            output_tokens=sum(item.output_tokens or 0 for item in completed),
            cost_usd=sum(
                (item.actual_cost_usd or Decimal("0") for item in completed),
                start=Decimal("0"),
            ),
        )

    return execute_deep_ai(operation)


@router.post(
    "/deep-ai/escalations/{escalation_job_id}/feedback",
    response_model=DeepAiLearningObservation,
    status_code=status.HTTP_201_CREATED,
)
def record_deep_ai_feedback(
    escalation_job_id: str,
    payload: DeepAiFeedbackRequest,
    request: Request,
) -> DeepAiLearningObservation:
    def operation() -> DeepAiLearningObservation:
        services = request.app.state.services
        job = services.deep_ai_repository.get_job(escalation_job_id)
        project_key = services.deep_ai.source_resolver.project_key_for(
            job.source_kind,
            job.source_id,
        )
        return DeepAiLearningLedger(services.deep_ai_repository).record_feedback(
            idempotency_key=payload.idempotency_key,
            project_key=project_key,
            job=job,
            action=DeepAiHumanAction(payload.action.value),
            reason_tags=payload.reason_tags,
            final_content_digest=payload.final_content_digest,
            downstream_ref=payload.downstream_ref,
        )

    return execute_deep_ai(operation)


@router.get("/deep-ai/learning", response_model=list[DeepAiLearningEvent])
def list_deep_ai_learning(
    request: Request,
    project_key: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[DeepAiLearningEvent]:
    return request.app.state.services.deep_ai_repository.list_learning_events(
        project_key=project_key,
        limit=limit,
    )


@router.post(
    "/deep-ai/evaluation-snapshots",
    response_model=QualityEvaluationSnapshot,
    status_code=status.HTTP_201_CREATED,
)
def create_quality_evaluation_snapshot(
    payload: QualityEvaluationSnapshotRequest,
    request: Request,
) -> QualityEvaluationSnapshot:
    return execute_deep_ai(
        lambda: request.app.state.services.quality_evaluation.create_snapshot(
            QualityEvaluationScope(**payload.model_dump())
        )
    )


@router.get(
    "/deep-ai/evaluation-snapshots",
    response_model=list[QualityEvaluationSnapshot],
)
def list_quality_evaluation_snapshots(
    request: Request,
    project_key: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[QualityEvaluationSnapshot]:
    return request.app.state.services.quality_evaluation.list_snapshots(
        project_key=project_key,
        limit=limit,
    )


@router.get(
    "/deep-ai/evaluation-snapshots/{snapshot_id}",
    response_model=QualityEvaluationSnapshot,
)
def get_quality_evaluation_snapshot(
    snapshot_id: str,
    request: Request,
) -> QualityEvaluationSnapshot:
    return execute_deep_ai(
        lambda: request.app.state.services.quality_evaluation.get_snapshot(snapshot_id)
    )


@router.post(
    "/deep-ai/evaluations",
    response_model=QualityEvaluationRun,
    status_code=status.HTTP_201_CREATED,
)
def create_quality_evaluation(
    payload: QualityEvaluationRunRequest,
    request: Request,
) -> QualityEvaluationRun:
    return execute_deep_ai(
        lambda: request.app.state.services.quality_evaluation.evaluate(payload.snapshot_id)
    )


@router.get("/deep-ai/evaluations", response_model=list[QualityEvaluationRun])
def list_quality_evaluations(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[QualityEvaluationRun]:
    return request.app.state.services.quality_evaluation.list_runs(limit=limit)


@router.get(
    "/deep-ai/evaluations/{evaluation_run_id}",
    response_model=QualityEvaluationRun,
)
def get_quality_evaluation(
    evaluation_run_id: str,
    request: Request,
) -> QualityEvaluationRun:
    return execute_deep_ai(
        lambda: request.app.state.services.quality_evaluation.get_run(evaluation_run_id)
    )


@router.post(
    "/deep-ai/evaluations/{evaluation_run_id}/reconcile",
    response_model=QualityEvaluationRun,
)
def reconcile_quality_evaluation(
    evaluation_run_id: str,
    payload: QualityEvaluationReconcileRequest,
    request: Request,
) -> QualityEvaluationRun:
    del payload
    return execute_deep_ai(
        lambda: request.app.state.services.quality_evaluation.reconcile(evaluation_run_id)
    )


@router.get(
    "/deep-ai/evaluations/{evaluation_run_id}/metrics",
    response_model=list[QualityEvaluationMetric],
)
def list_quality_evaluation_metrics(
    evaluation_run_id: str,
    request: Request,
) -> list[QualityEvaluationMetric]:
    return execute_deep_ai(
        lambda: request.app.state.services.quality_evaluation.list_metrics(evaluation_run_id)
    )


@router.get(
    "/deep-ai/improvement-candidates",
    response_model=list[QualityImprovementCandidate],
)
def list_quality_improvement_candidates(
    request: Request,
    evaluation_run_id: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[QualityImprovementCandidate]:
    return request.app.state.services.quality_evaluation.list_candidates(
        evaluation_run_id=evaluation_run_id,
        limit=limit,
    )


@router.get(
    "/deep-ai/improvement-candidates/{candidate_id}",
    response_model=QualityImprovementCandidate,
)
def get_quality_improvement_candidate(
    candidate_id: str,
    request: Request,
) -> QualityImprovementCandidate:
    return execute_deep_ai(
        lambda: request.app.state.services.quality_evaluation.get_candidate(candidate_id)
    )


@router.post(
    "/deep-ai/improvement-candidates/{candidate_id}/review",
    response_model=QualityImprovementCandidateReview,
    status_code=status.HTTP_201_CREATED,
)
def review_quality_improvement_candidate(
    candidate_id: str,
    payload: QualityImprovementReviewRequest,
    request: Request,
) -> QualityImprovementCandidateReview:
    return execute_deep_ai(
        lambda: request.app.state.services.quality_evaluation.review_candidate(
            candidate_id,
            action=payload.action.value,
            idempotency_key=payload.idempotency_key,
        )
    )


@router.post(
    "/deep-ai/shadow-runs",
    response_model=QualityShadowRun,
    status_code=status.HTTP_201_CREATED,
)
def create_quality_shadow_run(
    payload: QualityShadowRunRequest,
    request: Request,
) -> QualityShadowRun:
    return execute_deep_ai(
        lambda: request.app.state.services.quality_shadow.create(payload.candidate_id)
    )


@router.get("/deep-ai/shadow-runs", response_model=list[QualityShadowRun])
def list_quality_shadow_runs(
    request: Request,
    candidate_id: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[QualityShadowRun]:
    return request.app.state.services.quality_shadow.list_runs(
        candidate_id=candidate_id,
        limit=limit,
    )


@router.get(
    "/deep-ai/shadow-runs/{shadow_run_id}",
    response_model=QualityShadowRun,
)
def get_quality_shadow_run(
    shadow_run_id: str,
    request: Request,
) -> QualityShadowRun:
    return execute_deep_ai(
        lambda: request.app.state.services.quality_shadow.get_run(shadow_run_id)
    )


@router.post(
    "/deep-ai/shadow-runs/{shadow_run_id}/reconcile",
    response_model=QualityShadowRun,
)
def reconcile_quality_shadow_run(
    shadow_run_id: str,
    payload: QualityShadowReconcileRequest,
    request: Request,
) -> QualityShadowRun:
    del payload
    return execute_deep_ai(
        lambda: request.app.state.services.quality_shadow.reconcile(shadow_run_id)
    )


@router.get(
    "/deep-ai/shadow-runs/{shadow_run_id}/metrics",
    response_model=list[QualityShadowArmMetric],
)
def list_quality_shadow_metrics(
    shadow_run_id: str,
    request: Request,
) -> list[QualityShadowArmMetric]:
    return execute_deep_ai(
        lambda: request.app.state.services.quality_shadow.list_metrics(shadow_run_id)
    )


@router.post(
    "/deep-ai/shadow-runs/{shadow_run_id}/review",
    response_model=QualityShadowReview,
    status_code=status.HTTP_201_CREATED,
)
def review_quality_shadow_run(
    shadow_run_id: str,
    payload: QualityShadowReviewRequest,
    request: Request,
) -> QualityShadowReview:
    return execute_deep_ai(
        lambda: request.app.state.services.quality_shadow.review(
            shadow_run_id,
            action=payload.action.value,
            idempotency_key=payload.idempotency_key,
        )
    )


def execute_deep_ai[TResult](operation: Callable[[], TResult]) -> TResult:
    try:
        return operation()
    except KeyError as error:
        raise ApiError(
            status_code=404,
            code="DEEP_AI_RESOURCE_NOT_FOUND",
            message="Deep-AI resource not found.",
            retryable=False,
        ) from error
    except ValueError as error:
        raw_code = str(error)
        code = (
            raw_code
            if raw_code.startswith(("DEEP_AI_", "QUALITY_"))
            else "DEEP_AI_STATE_CONFLICT"
        )
        raise ApiError(
            status_code=409,
            code=code,
            message="Deep-AI operation conflicts with the bounded execution contract.",
            retryable=False,
        ) from error
