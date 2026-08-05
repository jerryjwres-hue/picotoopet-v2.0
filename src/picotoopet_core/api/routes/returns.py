"""Phase 10B-A 本地 Return 合同验证 REST 路由。"""

from fastapi import APIRouter, Depends, Header, Query, Request, status

from picotoopet_core.api.errors import ApiError
from picotoopet_core.returns.models import ReturnRecord
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/returns", response_model=list[ReturnRecord])
def list_returns(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
) -> list[ReturnRecord]:
    """返回最近的有界 Return 安全投影。"""

    return request.app.state.services.returns.list(limit=limit)


@router.get("/returns/{return_id}", response_model=ReturnRecord)
def get_return(return_id: str, request: Request) -> ReturnRecord:
    """读取一个 Return 的固定安全投影。"""

    return request.app.state.services.returns.get(return_id)


@router.post(
    "/handoffs/{handoff_id}/returns/self-test",
    response_model=ReturnRecord,
    status_code=status.HTTP_201_CREATED,
)
async def run_return_self_test(
    handoff_id: str,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=200,
        alias="Idempotency-Key",
    ),
) -> ReturnRecord:
    """运行服务器自有零变更 Return 演练；接口不接受任何包或参数正文。"""

    if await request.body():
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="本地 Return 合同演练不接受文件、路径、命令或任意请求正文。",
            retryable=False,
        )
    return request.app.state.services.returns.run_self_test(
        handoff_id,
        idempotency_key=idempotency_key,
    )
