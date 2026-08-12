"""Authenticated, bounded Deep-AI escalation and learning REST routes."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from enum import StrEnum

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.api.errors import ApiError
from picotoopet_core.deep_ai.learning import DeepAiLearningLedger, DeepAiLearningObservation
from picotoopet_core.deep_ai.models import (
    DeepAiEscalationRecord,
    DeepAiHumanAction,
    DeepAiLearningEvent,
)
from picotoopet_core.deep_ai.service import DeepAiReadiness
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
        context = services.deep_ai.source_resolver.resolve(job.source_kind, job.source_id)
        return DeepAiLearningLedger(services.deep_ai_repository).record_feedback(
            idempotency_key=payload.idempotency_key,
            project_key=context.project_key,
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
        code = str(error) if str(error).startswith("DEEP_AI_") else "DEEP_AI_STATE_CONFLICT"
        raise ApiError(
            status_code=409,
            code=code,
            message="Deep-AI operation conflicts with the bounded execution contract.",
            retryable=False,
        ) from error
