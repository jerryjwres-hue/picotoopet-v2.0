"""任务执行器只读状态路由。"""

from fastapi import APIRouter, Depends

from picotoopet_core.api.contracts import WorkerStatusResponse
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/workers/status", response_model=WorkerStatusResponse)
def worker_status() -> WorkerStatusResponse:
    """明确报告执行器尚未部署，不启动 Worker，也不领取历史任务。"""

    return WorkerStatusResponse()
