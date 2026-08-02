"""任务执行器只读状态路由。"""

from fastapi import APIRouter, Depends, Request

from picotoopet_core.api.contracts import WorkerStatusResponse
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/workers/status", response_model=WorkerStatusResponse)
def worker_status(request: Request) -> WorkerStatusResponse:
    """读取独立 Worker 的原子状态快照，不启动或领取任务。"""

    return request.app.state.services.worker_state.read_status()
