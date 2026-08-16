"""任务 REST 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request, status
from pydantic import ValidationError

from picotoopet_core.api.errors import ApiError
from picotoopet_core.diagnostics.models import (
    DiagnosticSnapshotRequest,
    DiagnosticSnapshotResult,
)
from picotoopet_core.domain.enums import CloudPolicy, TaskStatus
from picotoopet_core.domain.models import TaskCreate, TaskRecord
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.queue.state_machine import InvalidTransitionError
from picotoopet_core.research.models import ResearchSearchRequest, ResearchSearchResult
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])
_DIAGNOSTIC_TASK_TYPE = "system.diagnostic_snapshot"
_DIAGNOSTIC_DEDUPE_KEY = "system-diagnostic:active"
_RESEARCH_TASK_TYPE = "research.search"
_DIAGNOSTIC_RESULT_BYTES = 64 * 1024
_RESEARCH_RESULT_BYTES = 64 * 1024
_CONTROLLED_TASK_TYPES = {_DIAGNOSTIC_TASK_TYPE, _RESEARCH_TASK_TYPE}


def _required_idempotency_key(value: str | None) -> str:
    """冻结受限任务共用的幂等键校验。"""

    stable_key = value.strip() if value else ""
    if not stable_key or len(stable_key) > 200:
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Idempotency-Key 是必需字段，且长度不得超过 200。",
            retryable=False,
        )
    return stable_key


def _frozen_research_task(
    payload: TaskCreate,
    idempotency_key: str | None,
) -> TaskCreate:
    """把 Windows 通用任务请求收窄为固定 research.search 执行合同。"""

    stable_key = _required_idempotency_key(idempotency_key)
    try:
        research = ResearchSearchRequest.model_validate(payload.payload)
    except ValidationError as error:
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Research 搜索参数无效。",
            retryable=False,
        ) from error
    return TaskCreate(
        task_type=_RESEARCH_TASK_TYPE,
        payload=research.model_dump(mode="json"),
        priority=60,
        resource_tag="research-gateway",
        idempotency_key=stable_key,
        max_attempts=2,
        timeout_seconds=120,
        cloud_policy=CloudPolicy.LOCAL_ONLY,
    )


@router.post("/tasks", response_model=TaskRecord, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TaskRecord:
    """创建通用任务；诊断保留固定端点，Research 在服务端被严格冻结。"""

    if payload.task_type == _DIAGNOSTIC_TASK_TYPE:
        raise ApiError(
            status_code=422,
            code="RESERVED_TASK_TYPE",
            message="系统诊断快照必须使用固定诊断端点创建。",
            retryable=False,
        )
    if payload.task_type == _RESEARCH_TASK_TYPE:
        payload = _frozen_research_task(payload, idempotency_key)
    elif idempotency_key:
        payload = payload.model_copy(update={"idempotency_key": idempotency_key})
    return request.app.state.services.queue.create(
        payload,
        trace_id=request.state.trace_id,
    )


@router.post(
    "/tasks/system-diagnostic-snapshot",
    response_model=TaskRecord,
    status_code=status.HTTP_201_CREATED,
)
def create_system_diagnostic_snapshot(
    payload: DiagnosticSnapshotRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TaskRecord:
    """使用服务端冻结参数和调用方幂等键创建本地诊断任务。"""

    stable_key = _required_idempotency_key(idempotency_key)
    return request.app.state.services.queue.create(
        TaskCreate(
            task_type=_DIAGNOSTIC_TASK_TYPE,
            payload=payload.model_dump(mode="json"),
            priority=50,
            resource_tag="system-diagnostic",
            idempotency_key=stable_key,
            dedupe_key=_DIAGNOSTIC_DEDUPE_KEY,
            max_attempts=2,
            timeout_seconds=30,
            cloud_policy=CloudPolicy.LOCAL_ONLY,
        ),
        trace_id=request.state.trace_id,
    )


@router.post(
    "/tasks/research-search",
    response_model=TaskRecord,
    status_code=status.HTTP_201_CREATED,
)
def create_research_search(
    payload: ResearchSearchRequest,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TaskRecord:
    """固定端点同样保留，供未来非 Windows 客户端安全创建只读搜索。"""

    stable_key = _required_idempotency_key(idempotency_key)
    return request.app.state.services.queue.create(
        TaskCreate(
            task_type=_RESEARCH_TASK_TYPE,
            payload=payload.model_dump(mode="json"),
            priority=60,
            resource_tag="research-gateway",
            idempotency_key=stable_key,
            max_attempts=2,
            timeout_seconds=120,
            cloud_policy=CloudPolicy.LOCAL_ONLY,
        ),
        trace_id=request.state.trace_id,
    )


@router.get("/tasks/{task_id}", response_model=TaskRecord)
def get_task(task_id: str, request: Request) -> TaskRecord:
    """读取任务。"""

    return request.app.state.services.queue.get(task_id)


@router.post("/tasks/{task_id}/cancel", response_model=TaskRecord)
def cancel_task(task_id: str, request: Request) -> TaskRecord:
    """取消尚未完成的任务；Running 受限任务由 Worker 提交唯一终态。"""

    queue = request.app.state.services.queue
    task = queue.get(task_id)
    if task.task_type in _CONTROLLED_TASK_TYPES:
        if not isinstance(queue, DiagnosticQueueRepository):
            raise ApiError(
                status_code=503,
                code="WORKER_NOT_AVAILABLE",
                message="受限任务运行时尚未启用。",
                retryable=True,
            )
        return queue.request_cancel(
            task_id,
            trace_id=request.state.trace_id,
        )
    return queue.transition(
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


@router.get(
    "/tasks/{task_id}/result",
    response_model=DiagnosticSnapshotResult | ResearchSearchResult,
)
def get_task_result(
    task_id: str,
    request: Request,
) -> DiagnosticSnapshotResult | ResearchSearchResult:
    """读取已完成受限任务的固定结果合同，不提供任意 ResultStore 浏览接口。"""

    services = request.app.state.services
    task = services.queue.get(task_id)
    if task.task_type not in _CONTROLLED_TASK_TYPES:
        raise KeyError(f"任务没有开放固定结果合同：{task_id}")
    if task.status is not TaskStatus.COMPLETED or task.result_id is None:
        raise InvalidTransitionError("任务结果尚未可用。")

    try:
        metadata = services.result_records.get(task.result_id)
        if metadata.task_id != task_id or metadata.result_type != task.task_type:
            raise ValueError("结果元数据关联不一致。")
        max_bytes = (
            _DIAGNOSTIC_RESULT_BYTES
            if task.task_type == _DIAGNOSTIC_TASK_TYPE
            else _RESEARCH_RESULT_BYTES
        )
        document = services.results.read_json(
            metadata.object_hash,
            max_bytes=max_bytes,
        )
        if task.task_type == _DIAGNOSTIC_TASK_TYPE:
            return DiagnosticSnapshotResult.model_validate(document)
        return ResearchSearchResult.model_validate(document)
    except (KeyError, OSError, ValueError, ValidationError) as error:
        raise ApiError(
            status_code=500,
            code="RESULT_INTEGRITY_ERROR",
            message="任务结果完整性校验失败。",
            retryable=False,
        ) from error
