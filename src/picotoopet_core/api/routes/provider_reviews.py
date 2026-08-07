"""Phase 10D-B Provider Return 人工审阅 REST 路由。"""

from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, Query, Request

from picotoopet_core.api.errors import ApiError
from picotoopet_core.providers.review_models import (
    ProviderAdoptionCandidateRecord,
    ProviderReviewRecord,
)
from picotoopet_core.providers.review_service import (
    ProviderReviewConflict,
    ProviderReviewError,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get(
    "/provider-sessions/{session_id}/review",
    response_model=ProviderReviewRecord,
)
def get_provider_review(session_id: str, request: Request) -> ProviderReviewRecord:
    """返回重新验签的只读 Review 投影。"""

    return execute_review(
        lambda: request.app.state.services.provider_reviews.get_review(session_id)
    )


@router.post(
    "/provider-sessions/{session_id}/review/accept",
    response_model=ProviderReviewRecord,
)
async def accept_provider_review(
    session_id: str,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> ProviderReviewRecord:
    """空 body 接受 Review，并创建唯一落地候选。"""

    await require_empty_body(request)
    return execute_review(
        lambda: request.app.state.services.provider_reviews.accept(
            session_id,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/provider-sessions/{session_id}/review/reject",
    response_model=ProviderReviewRecord,
)
async def reject_provider_review(
    session_id: str,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> ProviderReviewRecord:
    """空 body 永久拒绝 Review；拒绝不创建候选。"""

    await require_empty_body(request)
    return execute_review(
        lambda: request.app.state.services.provider_reviews.reject(
            session_id,
            idempotency_key=idempotency_key,
        )
    )


@router.get(
    "/provider-adoption-candidates",
    response_model=list[ProviderAdoptionCandidateRecord],
)
def list_provider_adoption_candidates(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
) -> list[ProviderAdoptionCandidateRecord]:
    """返回最近的落地候选安全投影。"""

    return execute_review(
        lambda: request.app.state.services.provider_reviews.list_candidates(limit=limit)
    )


@router.get(
    "/provider-adoption-candidates/{candidate_id}",
    response_model=ProviderAdoptionCandidateRecord,
)
def get_provider_adoption_candidate(
    candidate_id: str,
    request: Request,
) -> ProviderAdoptionCandidateRecord:
    """返回一个落地候选安全投影。"""

    return execute_review(
        lambda: request.app.state.services.provider_reviews.get_candidate(candidate_id)
    )


async def require_empty_body(request: Request) -> None:
    """Review 决策禁止 patch、路径、reason 和任意自由 JSON。"""

    if await request.body():
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Provider Review 决策不接受任何请求正文。",
            retryable=False,
        )


def execute_review[TResult](operation: Callable[[], TResult]) -> TResult:
    """把 Review 领域错误映射为固定安全 API 错误。"""

    try:
        return operation()
    except KeyError as error:
        raise ApiError(
            status_code=404,
            code="ADOPTION_NOT_FOUND",
            message="Provider Review 或落地候选不存在。",
            retryable=False,
        ) from error
    except ProviderReviewConflict as error:
        raise ApiError(
            status_code=409,
            code=error.code,
            message="该 Review 已有不可反转的决策事实。",
            retryable=False,
        ) from error
    except ProviderReviewError as error:
        raise ApiError(
            status_code=400,
            code=error.code,
            message="Provider Review 当前不能执行该操作。",
            retryable=False,
        ) from error
