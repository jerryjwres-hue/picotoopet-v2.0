"""Phase 10B-B 固定 Mock Dev Broker Session REST 路由。"""

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends, Header, Query, Request, status

from picotoopet_core.api.errors import ApiError
from picotoopet_core.broker.lifecycle import mark_failed, mark_timed_out
from picotoopet_core.broker.models import (
    BrokerSessionCreateResult,
    BrokerSessionRecord,
    MockBrokerReturnEnvelope,
)
from picotoopet_core.broker.service import (
    BrokerSessionConflict,
    BrokerSessionError,
    BrokerSessionPolicyError,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])
TResult = TypeVar("TResult")


@router.get("/broker-sessions", response_model=list[BrokerSessionRecord])
def list_broker_sessions(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
) -> list[BrokerSessionRecord]:
    """返回最近的 Broker Session 安全投影；不包含 capability。"""

    return execute_broker(
        lambda: request.app.state.services.broker_sessions.list_sessions(limit=limit)
    )


@router.get(
    "/broker-sessions/{session_id}",
    response_model=BrokerSessionRecord,
)
def get_broker_session(session_id: str, request: Request) -> BrokerSessionRecord:
    """读取单个 Broker Session 安全投影。"""

    return execute_broker(
        lambda: request.app.state.services.broker_sessions.get_session(session_id)
    )


@router.post(
    "/handoffs/{handoff_id}/broker-sessions/mock",
    response_model=BrokerSessionCreateResult,
    status_code=status.HTTP_201_CREATED,
)
async def reserve_mock_broker_session(
    handoff_id: str,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> BrokerSessionCreateResult:
    """幂等预留固定 Mock Broker Session；接口不接受正文。"""

    await require_empty_body(request)
    return execute_broker(
        lambda: request.app.state.services.broker_sessions.reserve_mock_session(
            handoff_id,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/broker-sessions/{session_id}/start",
    response_model=BrokerSessionRecord,
)
async def start_mock_broker_session(
    session_id: str,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> BrokerSessionRecord:
    """记录 Windows 即将启动固定子进程，避免客户端伪造 running。"""

    del idempotency_key
    await require_empty_body(request)
    return execute_broker(
        lambda: request.app.state.services.broker_sessions.mark_running(session_id)
    )


@router.post(
    "/broker-sessions/{session_id}/cancel",
    response_model=BrokerSessionRecord,
)
async def cancel_mock_broker_session(
    session_id: str,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> BrokerSessionRecord:
    """记录取消事实；Windows 仍负责关闭 Job Object 和完整进程树。"""

    del idempotency_key
    await require_empty_body(request)
    return execute_broker(
        lambda: request.app.state.services.broker_sessions.cancel_session(session_id)
    )


@router.post(
    "/broker-sessions/{session_id}/timeout",
    response_model=BrokerSessionRecord,
)
async def timeout_mock_broker_session(
    session_id: str,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> BrokerSessionRecord:
    """记录固定 30 秒 Job Object 超时事实；接口不接受正文。"""

    del idempotency_key
    await require_empty_body(request)
    return execute_broker(
        lambda: mark_timed_out(
            request.app.state.services.broker_sessions,
            session_id,
        )
    )


@router.post(
    "/broker-sessions/{session_id}/fail",
    response_model=BrokerSessionRecord,
)
async def fail_mock_broker_session(
    session_id: str,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> BrokerSessionRecord:
    """记录固定 Broker 子进程失败事实；不接收错误正文或命令。"""

    del idempotency_key
    await require_empty_body(request)
    return execute_broker(
        lambda: mark_failed(
            request.app.state.services.broker_sessions,
            session_id,
        )
    )


@router.post(
    "/broker-sessions/{session_id}/return",
    response_model=BrokerSessionRecord,
)
def submit_mock_broker_return(
    session_id: str,
    envelope: MockBrokerReturnEnvelope,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
    session_capability: str = Header(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        alias="X-Picotoo-Broker-Session",
    ),
) -> BrokerSessionRecord:
    """提交严格、有界、Session 绑定的固定 Mock Return JSON。"""

    return execute_broker(
        lambda: request.app.state.services.broker_sessions.ingest_mock_return(
            session_id,
            envelope,
            capability=session_capability,
            idempotency_key=idempotency_key,
        )
    )


async def require_empty_body(request: Request) -> None:
    """固定状态命令不得携带路径、命令、凭据或任意 JSON。"""

    if await request.body():
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Broker Session 状态命令不接受任何请求正文。",
            retryable=False,
        )


def execute_broker(operation: Callable[[], TResult]) -> TResult:
    """把 Broker 领域错误转换为不泄漏内部正文的固定 API 错误。"""

    try:
        return operation()
    except BrokerSessionPolicyError as error:
        raise ApiError(
            status_code=400,
            code="BROKER_POLICY_DENIED",
            message=str(error),
            retryable=False,
        ) from error
    except BrokerSessionConflict as error:
        raise ApiError(
            status_code=409,
            code="BROKER_SESSION_CONFLICT",
            message=str(error),
            retryable=False,
        ) from error
    except BrokerSessionError as error:
        raise ApiError(
            status_code=400,
            code="BROKER_SESSION_ERROR",
            message=str(error),
            retryable=False,
        ) from error
