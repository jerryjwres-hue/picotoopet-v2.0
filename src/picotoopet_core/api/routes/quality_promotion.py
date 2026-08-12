"""Authenticated 2.3.25.1 Promotion / rollback governance routes."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.api.errors import ApiError
from picotoopet_core.deep_ai.promotion import (
    QualityPromotion,
    QualityPromotionApprovalRequest,
    QualityPromotionHistory,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


class QualityPromotionCreateRequest(BaseModel):
    """Promotion creation accepts only an already-reviewed immutable Shadow identity."""

    model_config = ConfigDict(extra="forbid")

    shadow_run_id: str = Field(min_length=1, max_length=160)


class QualityPromotionReconcileRequest(BaseModel):
    """Reconcile carries no caller policy or mutation authority."""

    model_config = ConfigDict(extra="forbid")


class QualityPromotionDecisionAction(StrEnum):
    """Closed exact human decisions for activation and rollback."""

    APPROVED = "Approved"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"


class QualityPromotionDecisionRequest(BaseModel):
    """Decision is bound to the exact server-issued request digest."""

    model_config = ConfigDict(extra="forbid")

    decision: QualityPromotionDecisionAction
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=1, max_length=256)


class QualityPromotionRollbackReason(StrEnum):
    """Closed rollback reason codes; arbitrary free-text policy cannot enter Core."""

    REGRESSION_OBSERVED = "RegressionObserved"
    UNEXPECTED_IMPACT = "UnexpectedImpact"
    OPERATOR_DECISION = "OperatorDecision"


class QualityPromotionRollbackRequest(BaseModel):
    """Rollback request accepts only one source-controlled reason code."""

    model_config = ConfigDict(extra="forbid")

    rollback_reason_code: QualityPromotionRollbackReason


@router.post(
    "/deep-ai/promotions",
    response_model=QualityPromotion,
    status_code=status.HTTP_201_CREATED,
)
def create_quality_promotion(
    payload: QualityPromotionCreateRequest,
    request: Request,
) -> QualityPromotion:
    return execute_quality_promotion(
        lambda: request.app.state.services.quality_promotion.create(payload.shadow_run_id)
    )


@router.get("/deep-ai/promotions", response_model=list[QualityPromotion])
def list_quality_promotions(
    request: Request,
    project_key: str | None = Query(default=None, max_length=200),
    candidate_class: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[QualityPromotion]:
    return request.app.state.services.quality_promotion.list_promotions(
        project_key=project_key,
        candidate_class=candidate_class,
        limit=limit,
    )


@router.get("/deep-ai/promotions/active", response_model=QualityPromotion | None)
def get_active_quality_promotion(
    request: Request,
    project_key: str = Query(min_length=1, max_length=200),
    candidate_class: str = Query(min_length=1, max_length=80),
) -> QualityPromotion | None:
    return request.app.state.services.quality_promotion.get_active(project_key, candidate_class)


@router.get("/deep-ai/promotions/{promotion_id}", response_model=QualityPromotion)
def get_quality_promotion(
    promotion_id: str,
    request: Request,
) -> QualityPromotion:
    return execute_quality_promotion(
        lambda: request.app.state.services.quality_promotion.get_promotion(promotion_id)
    )


@router.post(
    "/deep-ai/promotions/{promotion_id}/reconcile",
    response_model=QualityPromotion,
)
def reconcile_quality_promotion(
    promotion_id: str,
    payload: QualityPromotionReconcileRequest,
    request: Request,
) -> QualityPromotion:
    del payload
    return execute_quality_promotion(
        lambda: request.app.state.services.quality_promotion.reconcile(promotion_id)
    )


@router.get(
    "/deep-ai/promotions/{promotion_id}/activation-request",
    response_model=QualityPromotionApprovalRequest,
)
def get_quality_promotion_activation_request(
    promotion_id: str,
    request: Request,
) -> QualityPromotionApprovalRequest:
    return execute_quality_promotion(
        lambda: request.app.state.services.quality_promotion.get_activation_request(promotion_id)
    )


@router.post(
    "/deep-ai/promotions/{promotion_id}/activation-decision",
    response_model=QualityPromotion,
)
def decide_quality_promotion_activation(
    promotion_id: str,
    payload: QualityPromotionDecisionRequest,
    request: Request,
) -> QualityPromotion:
    return execute_quality_promotion(
        lambda: request.app.state.services.quality_promotion.decide_activation(
            promotion_id,
            decision=payload.decision.value,
            request_digest=payload.request_digest,
            idempotency_key=payload.idempotency_key,
        )
    )


@router.post(
    "/deep-ai/promotions/{promotion_id}/rollback-request",
    response_model=QualityPromotionApprovalRequest,
    status_code=status.HTTP_201_CREATED,
)
def request_quality_promotion_rollback(
    promotion_id: str,
    payload: QualityPromotionRollbackRequest,
    request: Request,
) -> QualityPromotionApprovalRequest:
    return execute_quality_promotion(
        lambda: request.app.state.services.quality_promotion.request_rollback(
            promotion_id,
            payload.rollback_reason_code.value,
        )
    )


@router.get(
    "/deep-ai/promotions/{promotion_id}/rollback-request",
    response_model=QualityPromotionApprovalRequest,
)
def get_quality_promotion_rollback_request(
    promotion_id: str,
    request: Request,
) -> QualityPromotionApprovalRequest:
    return execute_quality_promotion(
        lambda: request.app.state.services.quality_promotion.get_rollback_request(promotion_id)
    )


@router.post(
    "/deep-ai/promotions/{promotion_id}/rollback-decision",
    response_model=QualityPromotion,
)
def decide_quality_promotion_rollback(
    promotion_id: str,
    payload: QualityPromotionDecisionRequest,
    request: Request,
) -> QualityPromotion:
    return execute_quality_promotion(
        lambda: request.app.state.services.quality_promotion.decide_rollback(
            promotion_id,
            decision=payload.decision.value,
            request_digest=payload.request_digest,
            idempotency_key=payload.idempotency_key,
        )
    )


@router.get(
    "/deep-ai/promotions/{promotion_id}/history",
    response_model=QualityPromotionHistory,
)
def get_quality_promotion_history(
    promotion_id: str,
    request: Request,
) -> QualityPromotionHistory:
    return execute_quality_promotion(
        lambda: request.app.state.services.quality_promotion.history(promotion_id)
    )


def execute_quality_promotion[TResult](operation: Callable[[], TResult]) -> TResult:
    """Map closed governance conflicts without leaking internal persistence details."""

    try:
        return operation()
    except KeyError as error:
        raise ApiError(
            status_code=404,
            code="QUALITY_PROMOTION_RESOURCE_NOT_FOUND",
            message="Promotion governance resource not found.",
            retryable=False,
        ) from error
    except ValueError as error:
        raw_code = str(error)
        code = raw_code if raw_code.startswith("QUALITY_PROMOTION_") else "QUALITY_PROMOTION_CONFLICT"
        raise ApiError(
            status_code=409,
            code=code,
            message="Promotion governance operation conflicts with the bounded contract.",
            retryable=False,
        ) from error
