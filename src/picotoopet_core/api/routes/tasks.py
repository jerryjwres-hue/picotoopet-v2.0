"""任务 REST 路由。"""

from fastapi import APIRouter, Depends, Header, Query, Request, status
from pydantic import ValidationError

from picotoopet_core.api.errors import ApiError
from picotoopet_core.api.production_admission_hold import block_legacy_gpu_task
from picotoopet_core.domain.enums import CloudPolicy, TaskStatus
from picotoopet_core.domain.executor import (
    GPU_TAG,
    IMPORTED_TASK_TYPE,
    TASK_RUNNERS,
    ExecutorPayload,
)
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

    # 先检查 GPU 准入，再允许幂等重放/执行器 payload；设备 Bearer 无法自己放行。
    block_legacy_gpu_task(request, payload)
    if idempotency_key:
        payload = payload.model_copy(update={"idempotency_key": idempotency_key})
    if payload.task_type == IMPORTED_TASK_TYPE:
        raise ApiError(
            status_code=422, code="VALIDATION_ERROR", retryable=False,
            message="历史记录须通过剧集导入接口生成。",
        )
    if payload.task_type in TASK_RUNNERS:
        try:
            body = ExecutorPayload.model_validate(payload.payload)
        except ValidationError as exc:
            fields = "、".join(".".join(map(str, item["loc"])) for item in exc.errors())
            raise ApiError(
                status_code=422, code="VALIDATION_ERROR", retryable=False,
                message=f"执行任务 payload 字段无效：{fields}。",
            ) from exc
        if (
            body.runner != TASK_RUNNERS[payload.task_type]
            or payload.cloud_policy is not CloudPolicy.LOCAL_ONLY
        ):
            raise ApiError(status_code=422, code="VALIDATION_ERROR",
                           message="执行任务须使用对应的本地 runner。", retryable=False)
        if payload.task_type == "edit.assemble":
            return request.app.state.services.production.assemble(
                body.episode_id, request.state.trace_id,
            )
        payload = payload.model_copy(update={
            "resource_tag": payload.resource_tag or GPU_TAG,
            "payload": body.model_dump(mode="json"),
        })
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

    services = request.app.state.services
    original = services.queue.get(task_id)
    block_legacy_gpu_task(request, TaskCreate(
        task_type=original.task_type,
        resource_tag=original.resource_tag,
    ))
    if original.task_type in TASK_RUNNERS:
        return services.executor.retry(task_id, request.state.trace_id)
    return services.queue.retry(
        task_id,
        trace_id=request.state.trace_id,
    )
