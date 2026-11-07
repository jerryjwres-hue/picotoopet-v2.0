"""Loopback-only authenticated Owner Structured Review API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status

from picotoopet_core.api.errors import ApiError
from picotoopet_core.autonomous.owner_structured_review import (
    OwnerStructuredReviewCommit,
    OwnerStructuredReviewCommitRequest,
    OwnerStructuredReviewError,
    OwnerStructuredReviewPreview,
    OwnerStructuredReviewPreviewRequest,
    OwnerStructuredReviewProposal,
    OwnerStructuredReviewService,
)
from picotoopet_core.security.owner_auth import require_owner_principal
from picotoopet_core.security.owner_principal import OwnerPrincipal

router = APIRouter()
OwnerIdentity = Annotated[OwnerPrincipal, Depends(require_owner_principal)]


def _service(request: Request) -> OwnerStructuredReviewService:
    return OwnerStructuredReviewService(request.app.state.services.database)


def _raise_review_error(error: OwnerStructuredReviewError) -> None:
    raise ApiError(
        status_code=error.status_code,
        code=error.code,
        message="主人结构化审核请求与当前 Core 事实不匹配。",
        retryable=False,
    ) from error


@router.get(
    "/owner-structured-reviews/goals/{goal_id}/proposal",
    response_model=OwnerStructuredReviewProposal,
)
def get_owner_structured_review_proposal(
    goal_id: str,
    request: Request,
    principal: OwnerIdentity,
) -> OwnerStructuredReviewProposal:
    """Return a read-only, source-derived typed proposal without evidence body text."""

    try:
        return _service(request).proposal(goal_id, principal)
    except OwnerStructuredReviewError as error:
        _raise_review_error(error)


@router.post(
    "/owner-structured-reviews/preview",
    response_model=OwnerStructuredReviewPreview,
)
def preview_owner_structured_review(
    payload: OwnerStructuredReviewPreviewRequest,
    request: Request,
    principal: OwnerIdentity,
) -> OwnerStructuredReviewPreview:
    """Apply field decisions and calculate digests without any database write."""

    try:
        return _service(request).preview(payload, principal)
    except OwnerStructuredReviewError as error:
        _raise_review_error(error)


@router.post(
    "/owner-structured-reviews/commit",
    response_model=OwnerStructuredReviewCommit,
    status_code=status.HTTP_201_CREATED,
)
def commit_owner_structured_review(
    payload: OwnerStructuredReviewCommitRequest,
    request: Request,
    principal: OwnerIdentity,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> OwnerStructuredReviewCommit:
    """Atomically persist one exact, fresh and explicitly authorized preview."""

    try:
        return _service(request).commit(
            payload,
            principal,
            idempotency_key=idempotency_key,
        )
    except OwnerStructuredReviewError as error:
        _raise_review_error(error)
