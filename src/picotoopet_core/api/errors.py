"""统一 API 错误模型和处理器。"""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from picotoopet_core.approvals.service import ApprovalError
from picotoopet_core.handoffs.service import HandoffConflict, HandoffError, HandoffPolicyError
from picotoopet_core.queue.state_machine import InvalidTransitionError
from picotoopet_core.returns.service import ReturnConflict, ReturnError, ReturnPolicyError


class ErrorBody(BaseModel):
    """客户端可稳定处理的错误内容。"""

    code: str
    message: str
    retryable: bool
    trace_id: str


class ApiError(RuntimeError):
    """预期业务错误。"""

    def __init__(self, *, status_code: int, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable


def install_error_handlers(app: FastAPI) -> None:
    """安装统一错误外壳。"""

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        trace_id = request.headers.get("X-Picotoo-Trace-Id", str(uuid4()))
        payload = ErrorBody(
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            trace_id=trace_id,
        )
        return JSONResponse(status_code=exc.status_code, content={"error": payload.model_dump()})

    @app.exception_handler(ApprovalError)
    async def handle_approval_error(request: Request, exc: ApprovalError) -> JSONResponse:
        """把审批令牌、过期和重放错误转换为冲突响应。"""

        trace_id = request.headers.get("X-Picotoo-Trace-Id", str(uuid4()))
        payload = ErrorBody(
            code="CONFLICT",
            message=str(exc),
            retryable=False,
            trace_id=trace_id,
        )
        return JSONResponse(status_code=409, content={"error": payload.model_dump()})

    @app.exception_handler(HandoffPolicyError)
    async def handle_handoff_policy_error(
        request: Request,
        exc: HandoffPolicyError,
    ) -> JSONResponse:
        """把固定 Handoff 安全策略拒绝转换为非重试请求错误。"""

        trace_id = request.headers.get("X-Picotoo-Trace-Id", str(uuid4()))
        payload = ErrorBody(
            code="HANDOFF_POLICY_DENIED",
            message=str(exc),
            retryable=False,
            trace_id=trace_id,
        )
        return JSONResponse(status_code=400, content={"error": payload.model_dump()})

    @app.exception_handler(HandoffConflict)
    async def handle_handoff_conflict(
        request: Request,
        exc: HandoffConflict,
    ) -> JSONResponse:
        """把 Handoff 幂等或状态冲突转换为 409。"""

        trace_id = request.headers.get("X-Picotoo-Trace-Id", str(uuid4()))
        payload = ErrorBody(
            code="HANDOFF_CONFLICT",
            message=str(exc),
            retryable=False,
            trace_id=trace_id,
        )
        return JSONResponse(status_code=409, content={"error": payload.model_dump()})

    @app.exception_handler(HandoffError)
    async def handle_handoff_error(request: Request, exc: HandoffError) -> JSONResponse:
        """处理其他有界 Handoff 领域错误。"""

        trace_id = request.headers.get("X-Picotoo-Trace-Id", str(uuid4()))
        payload = ErrorBody(
            code="HANDOFF_ERROR",
            message=str(exc),
            retryable=False,
            trace_id=trace_id,
        )
        return JSONResponse(status_code=400, content={"error": payload.model_dump()})

    @app.exception_handler(ReturnPolicyError)
    async def handle_return_policy_error(
        request: Request,
        exc: ReturnPolicyError,
    ) -> JSONResponse:
        """把固定 Return 安全策略拒绝转换为非重试请求错误。"""

        trace_id = request.headers.get("X-Picotoo-Trace-Id", str(uuid4()))
        payload = ErrorBody(
            code="RETURN_POLICY_DENIED",
            message=str(exc),
            retryable=False,
            trace_id=trace_id,
        )
        return JSONResponse(status_code=400, content={"error": payload.model_dump()})

    @app.exception_handler(ReturnConflict)
    async def handle_return_conflict(
        request: Request,
        exc: ReturnConflict,
    ) -> JSONResponse:
        """把 Return 幂等或资源绑定冲突转换为 409。"""

        trace_id = request.headers.get("X-Picotoo-Trace-Id", str(uuid4()))
        payload = ErrorBody(
            code="RETURN_CONFLICT",
            message=str(exc),
            retryable=False,
            trace_id=trace_id,
        )
        return JSONResponse(status_code=409, content={"error": payload.model_dump()})

    @app.exception_handler(ReturnError)
    async def handle_return_error(request: Request, exc: ReturnError) -> JSONResponse:
        """处理其他有界 Return 领域错误。"""

        trace_id = request.headers.get("X-Picotoo-Trace-Id", str(uuid4()))
        payload = ErrorBody(
            code="RETURN_ERROR",
            message=str(exc),
            retryable=False,
            trace_id=trace_id,
        )
        return JSONResponse(status_code=400, content={"error": payload.model_dump()})

    @app.exception_handler(InvalidTransitionError)
    async def handle_transition_error(
        request: Request,
        exc: InvalidTransitionError,
    ) -> JSONResponse:
        """把非法任务状态转换转换为冲突响应。"""

        trace_id = request.headers.get("X-Picotoo-Trace-Id", str(uuid4()))
        payload = ErrorBody(
            code="CONFLICT",
            message=str(exc),
            retryable=False,
            trace_id=trace_id,
        )
        return JSONResponse(status_code=409, content={"error": payload.model_dump()})

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """把 Pydantic/FastAPI 校验错误转换为统一错误外壳。"""

        trace_id = request.headers.get("X-Picotoo-Trace-Id", str(uuid4()))
        payload = ErrorBody(
            code="VALIDATION_ERROR",
            message="请求参数不符合接口契约。",
            retryable=False,
            trace_id=trace_id,
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": payload.model_dump(),
                "validation": [
                    {
                        "location": list(item.get("loc", ())),
                        "type": item.get("type", "validation_error"),
                    }
                    for item in exc.errors()
                ],
            },
        )

    @app.exception_handler(KeyError)
    async def handle_not_found(request: Request, exc: KeyError) -> JSONResponse:
        trace_id = request.headers.get("X-Picotoo-Trace-Id", str(uuid4()))
        payload = ErrorBody(
            code="NOT_FOUND",
            message=str(exc).strip("'"),
            retryable=False,
            trace_id=trace_id,
        )
        return JSONResponse(status_code=404, content={"error": payload.model_dump()})
