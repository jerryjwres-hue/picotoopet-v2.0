"""Phase 10E Publication Candidate REST 路由。"""

from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, Query, Request

from picotoopet_core.api.errors import ApiError
from picotoopet_core.providers.publication_models import ProviderPublicationCandidateRecord
from picotoopet_core.providers.publication_service import (
    ProviderPublicationConflict,
    ProviderPublicationError,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post(
    "/provider-commit-candidates/{commit_candidate_id}/publication/prepare",
    response_model=ProviderPublicationCandidateRecord,
)
async def prepare_provider_publication(
    commit_candidate_id: str,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> ProviderPublicationCandidateRecord:
    """空 body 准备一次 exact Push + Draft PR 的 digest-bound 审批。"""

    await require_empty_body(request)
    return execute_publication(
        lambda: request.app.state.services.provider_publications.prepare(
            commit_candidate_id,
            idempotency_key=idempotency_key,
        )
    )


@router.get(
    "/provider-publication-candidates",
    response_model=list[ProviderPublicationCandidateRecord],
)
def list_provider_publication_candidates(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
) -> list[ProviderPublicationCandidateRecord]:
    return execute_publication(
        lambda: request.app.state.services.provider_publications.list_candidates(limit=limit)
    )


@router.get(
    "/provider-publication-candidates/{publication_candidate_id}",
    response_model=ProviderPublicationCandidateRecord,
)
def get_provider_publication_candidate(
    publication_candidate_id: str,
    request: Request,
) -> ProviderPublicationCandidateRecord:
    return execute_publication(
        lambda: request.app.state.services.provider_publications.get_candidate(
            publication_candidate_id
        )
    )


async def require_empty_body(request: Request) -> None:
    """Publication prepare 禁止 repo、ref、base、head、title、body 或任意自由 JSON。"""

    if await request.body():
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Publication Candidate 准备不接受任何请求正文。",
            retryable=False,
        )


def execute_publication[TResult](operation: Callable[[], TResult]) -> TResult:
    try:
        return operation()
    except KeyError as error:
        raise ApiError(
            status_code=404,
            code="PUBLICATION_NOT_FOUND",
            message="Publication Candidate 或对应 Commit Candidate 不存在。",
            retryable=False,
        ) from error
    except ProviderPublicationConflict as error:
        raise ApiError(
            status_code=409,
            code=error.code,
            message="该 Commit Candidate 已有不可重复的 Publication Candidate 事实。",
            retryable=False,
        ) from error
    except ProviderPublicationError as error:
        raise ApiError(
            status_code=400,
            code=error.code,
            message="Publication Candidate 当前不能执行该操作。",
            retryable=False,
        ) from error
