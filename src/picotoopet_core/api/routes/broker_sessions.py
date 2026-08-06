"""Phase 10B-B 固定 Mock Dev Broker Session REST 路由。"""

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from picotoopet_core.api.errors import ApiError
from picotoopet_core.broker.models import (
    BrokerSessionCreateResult,
    BrokerSessionRecord,
    MockBrokerReturnEnvelope,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/broker-sessions", response_model=list[BrokerSessionRecord])
def list_broker_sessions(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
) -> list[BrokerSessionRecord]:
    """返回最近的 Broker Session 安全投影；不包含 capability。"""

    return request.app.state.services.broker_sessions.list_sessions(limit=limit)


@router.get(
    "/broker-sessions/{session_id}",
    response_model=BrokerSessionRecord,
)
def get_broker_session(session_id: str, request: Request) -> BrokerSessionRecord:
    """读取单个 Broker Session 安全投影。"""

    return request.app.state.services.broker_sessions.get_session(session_id)


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
    return request.app.state.services.broker_sessions.reserve_mock_session(
        handoff_id,
        idempotency_key=idempotency_key,
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
    return request.app.state.services.broker_sessions.mark_running(session_id)


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
    return request.app.state.services.broker_sessions.cancel_session(session_id)


@router.post(
    "/broker-sessions/{session_id}/return",
    response_model=BrokerSessionRecord,
)
def submit_mock_broker_return(
    session_id: str,
    envelope: MockBrokerReturnEnvelope,
    request: Request,
    response: Response,
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

    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        raise ApiError(
            status_code=415,
            code="BROKER_OUTPUT_INVALID",
            message="Mock Broker Return 只接受 application/json。",
            retryable=False,
        )
    record = request.app.state.services.broker_sessions.ingest_mock_return(
        session_id,
        envelope,
        capability=session_capability,
        idempotency_key=idempotency_key,
    )
    response.status_code = status.HTTP_200_OK
    return record


async def require_empty_body(request: Request) -> None:
    """固定状态命令不得携带路径、命令、凭据或任意 JSON。"""

    if await request.body():
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Broker Session 状态命令不接受任何请求正文。",
            retryable=False,
        )
