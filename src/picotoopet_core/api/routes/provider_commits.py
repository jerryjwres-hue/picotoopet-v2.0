"""Phase 10D-C 本地 Commit Candidate REST 路由。"""

from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, Query, Request

from picotoopet_core.api.errors import ApiError
from picotoopet_core.providers.commit_models import ProviderCommitCandidateRecord
from picotoopet_core.providers.commit_service import (
    ProviderCommitConflict,
    ProviderCommitError,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post(
    "/provider-adoption-candidates/{candidate_id}/commit/prepare",
    response_model=ProviderCommitCandidateRecord,
)
async def prepare_provider_commit(
    candidate_id: str,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> ProviderCommitCandidateRecord:
    """空 body 准备一次 digest-bound 本地 Commit Candidate 审批。"""

    await require_empty_body(request)
    return execute_commit(
        lambda: request.app.state.services.provider_commits.prepare(
            candidate_id,
            idempotency_key=idempotency_key,
        )
    )


@router.get(
    "/provider-commit-candidates",
    response_model=list[ProviderCommitCandidateRecord],
)
def list_provider_commit_candidates(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
) -> list[ProviderCommitCandidateRecord]:
    """返回最近的本地 Commit Candidate 安全投影。"""

    return execute_commit(
        lambda: request.app.state.services.provider_commits.list_candidates(limit=limit)
    )


@router.get(
    "/provider-commit-candidates/{commit_candidate_id}",
    response_model=ProviderCommitCandidateRecord,
)
def get_provider_commit_candidate(
    commit_candidate_id: str,
    request: Request,
) -> ProviderCommitCandidateRecord:
    """返回一个本地 Commit Candidate 安全投影。"""

    return execute_commit(
        lambda: request.app.state.services.provider_commits.get_candidate(commit_candidate_id)
    )


async def require_empty_body(request: Request) -> None:
    """Commit prepare 禁止 message、ref、path、author、remote 和任意自由 JSON。"""

    if await request.body():
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Commit Candidate 准备不接受任何请求正文。",
            retryable=False,
        )


def execute_commit[TResult](operation: Callable[[], TResult]) -> TResult:
    """把 Commit Candidate 领域错误映射为固定安全 API 错误。"""

    try:
        return operation()
    except KeyError as error:
        raise ApiError(
            status_code=404,
            code="COMMIT_NOT_FOUND",
            message="Commit Candidate 或对应 Adoption Candidate 不存在。",
            retryable=False,
        ) from error
    except ProviderCommitConflict as error:
        raise ApiError(
            status_code=409,
            code=error.code,
            message="该 Adoption Candidate 已有不可重复的 Commit Candidate 事实。",
            retryable=False,
        ) from error
    except ProviderCommitError as error:
        raise ApiError(
            status_code=400,
            code=error.code,
            message="Commit Candidate 当前不能执行该操作。",
            retryable=False,
        ) from error
