"""任务 REST 路由。"""

from fastapi import APIRouter, Depends, Header, Query, Request, status

from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskCreate, TaskRecord
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/tasks", response_model=TaskRecord, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TaskRecord:
    """创建本地或人工审批任务。"""

    if idempotency_key:
        payload = payload.model_copy(update={"idempotency_key": idempotency_key})
    return request.app.state.services.queue.create(
        payload,
        trace_id=request.state.trace_id,
    )


@router.get("/tasks/{task_id}", response_model=TaskRecord)
def get_task(task_id: str, request: Request) -> TaskRecord:
    """读取任务。"""

    return request.app.state.services.queue.get(task_id)


@router.post("/tasks/{task_id}/cancel", response_model=TaskRecord)
def cancel_task(task_id: str, request: Request) -> TaskRecord:
    """取消尚未进入不可逆终态的任务。"""

    return request.app.state.services.queue.transition(
        task_id,
        TaskStatus.CANCELLED,
        reason="api_cancel",
        trace_id=request.state.trace_id,
    )


@router.get("/tasks", response_model=list[TaskRecord])
def list_tasks(
    request: Request,
    exclude_resource_tag: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[TaskRecord]:
    """返回有界任务快照；桌面可排除高样本诊断任务以降低传输和内存开销。"""

    return request.app.state.services.queue.list(
        exclude_resource_tag=exclude_resource_tag,
        limit=limit,
    )


@router.post("/tasks/{task_id}/retry", response_model=TaskRecord)
def retry_task(task_id: str, request: Request) -> TaskRecord:
    """创建新的子任务，不重新打开原终态任务。"""

    return request.app.state.services.queue.retry(
        task_id,
        trace_id=request.state.trace_id,
    )
