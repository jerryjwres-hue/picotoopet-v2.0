"""Bounded Codex and Claude Code Provider REST routes."""

from collections.abc import Callable

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


@router.get("/providers/codex/status", response_model=ProviderStatusRecord)
def get_codex_status(request: Request) -> ProviderStatusRecord:
    """Read the minimal Codex readiness projection without credentials or Usage data."""

    return execute_provider(
        lambda: request.app.state.services.provider_sessions.provider_status("codex")
    )


@router.get("/providers/claude-code/status", response_model=ProviderStatusRecord)
def get_claude_code_status(request: Request) -> ProviderStatusRecord:
    """Read the minimal Claude Code readiness projection without credentials or Usage data."""

    return execute_provider(
        lambda: request.app.state.services.provider_sessions.provider_status("claude_code")
    )


@router.post(
    "/handoffs/{handoff_id}/provider-usage-confirmation",
    response_model=ProviderUsageConfirmationRecord,
    status_code=status.HTTP_201_CREATED,
)
def confirm_provider_usage(
    handoff_id: str,
    body: ProviderUsageConfirmationRequest,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> ProviderUsageConfirmationRecord:
    """Record one short-lived usage fact for the provider already bound by the Handoff."""

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
    """Create the unique low-budget Session for an approved Codex Handoff."""

    await require_empty_body(request)
    return execute_provider(
        lambda: request.app.state.services.provider_sessions.create_codex_session(
            handoff_id,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/handoffs/{handoff_id}/provider-sessions/claude-code",
    response_model=ProviderSessionRecord,
    status_code=status.HTTP_201_CREATED,
)
async def create_claude_code_session(
    handoff_id: str,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> ProviderSessionRecord:
    """Create the unique low-budget Session for an approved Claude Code Handoff."""

    await require_empty_body(request)
    return execute_provider(
        lambda: request.app.state.services.provider_sessions.create_claude_code_session(
            handoff_id,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/provider-sessions", response_model=list[ProviderSessionRecord])
def list_provider_sessions(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
) -> list[ProviderSessionRecord]:
    """Read recent Provider Session safe projections."""

    return execute_provider(
        lambda: request.app.state.services.provider_sessions.list_sessions(limit=limit)
    )


@router.get(
    "/provider-sessions/{session_id}",
    response_model=ProviderSessionRecord,
)
def get_provider_session(session_id: str, request: Request) -> ProviderSessionRecord:
    """Read one Provider Session safe projection."""

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
    """Record cancellation; Mac Worker terminates the process group and cleans worktree."""

    del idempotency_key
    await require_empty_body(request)
    return execute_provider(
        lambda: request.app.state.services.provider_sessions.cancel_session(session_id)
    )


async def require_empty_body(request: Request) -> None:
    """Session create/cancel never accepts paths, commands, models, credentials or flags."""

    if await request.body():
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Provider Session 命令不接受任何请求正文。",
            retryable=False,
        )


def execute_provider[TResult](operation: Callable[[], TResult]) -> TResult:
    """Map Provider domain failures to fixed non-secret API errors."""

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
