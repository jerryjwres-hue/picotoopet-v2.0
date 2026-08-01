"""统一 API 错误模型和处理器。"""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from picotoopet_core.approvals.service import ApprovalError
from picotoopet_core.queue.state_machine import InvalidTransitionError


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
        self.code        = code
        self.message     = message
        self.retryable   = retryable


def install_error_handlers(app: FastAPI) -> None:
    """安装统一错误外壳。"""

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        trace_id = request.headers.get("X-Picotoo-Trace-Id", str(uuid4()))
        payload  = ErrorBody(
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
        payload  = ErrorBody(
            code="CONFLICT",
            message=str(exc),
            retryable=False,
            trace_id=trace_id,
        )
        return JSONResponse(status_code=409, content={"error": payload.model_dump()})

    @app.exception_handler(InvalidTransitionError)
    async def handle_transition_error(
        request: Request,
        exc: InvalidTransitionError,
    ) -> JSONResponse:
        """把非法任务状态转换转换为冲突响应。"""

        trace_id = request.headers.get("X-Picotoo-Trace-Id", str(uuid4()))
        payload  = ErrorBody(
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
        payload  = ErrorBody(
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
        payload  = ErrorBody(
            code="NOT_FOUND",
            message=str(exc).strip("'"),
            retryable=False,
            trace_id=trace_id,
        )
        return JSONResponse(status_code=404, content={"error": payload.model_dump()})
