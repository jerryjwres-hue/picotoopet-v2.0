"""Phase 10D-A 受控 Codex Provider REST 路由。"""

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends, Header, Query, Request, status

from picotoopet_core.api.errors import ApiError
from picotoopet_core.providers.models import (
    ProviderSessionRecord,
    ProviderStatusRecord,
    ProviderUsageConfirmationRecord,
    ProviderUsageConfirmationRequest,
)
from picotoopet_core.providers.service import (
    ProviderSessionConflict,
    ProviderSessionError,
    ProviderSessionPolicyError,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])
TResult = TypeVar("TResult")


@router.get("/providers/codex/status", response_model=ProviderStatusRecord)
def get_codex_status(request: Request) -> ProviderStatusRecord:
    """读取 Mac Worker 投影的最小就绪状态，不读取凭据或 Usage 页面。"""

    return execute_provider(
        lambda: request.app.state.services.provider_sessions.provider_status()
    )


@router.post(
    "/handoffs/{handoff_id}/provider-usage-confirmation",
    response_model=ProviderUsageConfirmationRecord,
    status_code=status.HTTP_201_CREATED,
)
def confirm_codex_usage(
    handoff_id: str,
    body: ProviderUsageConfirmationRequest,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> ProviderUsageConfirmationRecord:
    """记录用户在外部 Codex Usage 页面完成的短期人工确认。"""

    return execute_provider(
        lambda: request.app.state.services.provider_sessions.confirm_usage(
            handoff_id,
            body.status,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/handoffs/{handoff_id}/provider-sessions/codex",
    response_model=ProviderSessionRecord,
    status_code=status.HTTP_201_CREATED,
)
async def create_codex_session(
    handoff_id: str,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> ProviderSessionRecord:
    """为 approved Codex Handoff 幂等创建唯一低预算 Session。"""

    await require_empty_body(request)
    return execute_provider(
        lambda: request.app.state.services.provider_sessions.create_codex_session(
            handoff_id,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/provider-sessions", response_model=list[ProviderSessionRecord])
def list_provider_sessions(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
) -> list[ProviderSessionRecord]:
    """读取最近的 Provider Session 安全投影。"""

    return execute_provider(
        lambda: request.app.state.services.provider_sessions.list_sessions(limit=limit)
    )


@router.get(
    "/provider-sessions/{session_id}",
    response_model=ProviderSessionRecord,
)
def get_provider_session(session_id: str, request: Request) -> ProviderSessionRecord:
    """读取单个 Provider Session 安全投影。"""

    return execute_provider(
        lambda: request.app.state.services.provider_sessions.get_session(session_id)
    )


@router.post(
    "/provider-sessions/{session_id}/cancel",
    response_model=ProviderSessionRecord,
)
async def cancel_provider_session(
    session_id: str,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> ProviderSessionRecord:
    """记录取消事实；Mac Worker 负责终止完整进程组并清理 worktree。"""

    del idempotency_key
    await require_empty_body(request)
    return execute_provider(
        lambda: request.app.state.services.provider_sessions.cancel_session(session_id)
    )


async def require_empty_body(request: Request) -> None:
    """Session 创建和取消不接受路径、命令、模型、凭据或任意 JSON。"""

    if await request.body():
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Provider Session 命令不接受任何请求正文。",
            retryable=False,
        )


def execute_provider(operation: Callable[[], TResult]) -> TResult:
    """把 Provider 领域错误映射为固定、不泄密的 API 错误。"""

    try:
        return operation()
    except KeyError as error:
        raise ApiError(
            status_code=404,
            code="PROVIDER_SESSION_NOT_FOUND",
            message="Provider Session 不存在。",
            retryable=False,
        ) from error
    except ProviderSessionPolicyError as error:
        raise ApiError(
            status_code=400,
            code="PROVIDER_POLICY_DENIED",
            message=str(error),
            retryable=False,
        ) from error
    except ProviderSessionConflict as error:
        raise ApiError(
            status_code=409,
            code="PROVIDER_SESSION_CONFLICT",
            message=str(error),
            retryable=False,
        ) from error
    except ProviderSessionError as error:
        raise ApiError(
            status_code=400,
            code="PROVIDER_SESSION_ERROR",
            message=str(error),
            retryable=False,
        ) from error
