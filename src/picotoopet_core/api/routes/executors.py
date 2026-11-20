"""执行器、缩略图和审片 REST 路由。"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile

from picotoopet_core.api.thumbnails import validate_thumbnail
from picotoopet_core.api.production_admission_hold import storypack_owner_hold
from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.executor import (
    TASK_RUNNERS,
    THUMBNAIL_LIMIT,
    ArtifactDecision,
    ArtifactList,
    ExecutorComplete,
    ExecutorFail,
    ExecutorHeartbeat,
    ExecutorLease,
    ExecutorReport,
    ReviewedArtifact,
    Sha256,
    ThumbnailContent,
    ThumbnailRecord,
)
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post(
    "/executors/lease", response_model=TaskRecord, responses={204: {"description": "无任务"}}
)
def lease(body: ExecutorLease, request: Request) -> TaskRecord | Response:
    if storypack_owner_hold(request):
        # 仅允许已有 Journal 的同 Worker 有效租约恢复；不允许新租约或自动重试。
        # 注意不能调用 executor.lease(): 它会恢复旧任务并领取下一项，可能触发新 GPU POST。
        if body.resume_task_id is None:
            return Response(status_code=204)
        services = request.app.state.services
        row = services.database.fetchone(
            """SELECT status, task_type, resource_tag, lease_owner, lease_expires_at
               FROM tasks WHERE task_id = ?""",
            (body.resume_task_id,),
        )
        if (
            row is None
            or row["status"] != TaskStatus.RUNNING.value
            or row["task_type"] not in TASK_RUNNERS
            or row["resource_tag"] not in body.resource_tags
            or row["lease_owner"] != body.worker_id
            or row["lease_expires_at"] is None
            or datetime.fromisoformat(row["lease_expires_at"]) <= datetime.now(UTC)
        ):
            return Response(status_code=204)
        # 只读返回同一条租约；心跳/回执仍由原来的严格 Owned 校验负责。
        return services.queue.get(body.resume_task_id)
    return request.app.state.services.executor.lease(body, request.state.trace_id) or Response(
        status_code=204,
    )


@router.post("/tasks/{task_id}/heartbeat", responses={409: {"description": "租约不匹配"}})
def heartbeat(task_id: str, body: ExecutorHeartbeat, request: Request) -> TaskRecord:
    return request.app.state.services.executor.heartbeat(task_id, body, request.state.trace_id)


@router.post("/tasks/{task_id}/complete", responses={409: {"description": "租约不匹配"}})
def complete(task_id: str, body: ExecutorComplete, request: Request) -> TaskRecord:
    return request.app.state.services.executor.report(task_id, body, request.state.trace_id)


@router.post("/tasks/{task_id}/fail", responses={409: {"description": "租约不匹配"}})
def fail(task_id: str, body: ExecutorFail, request: Request) -> TaskRecord:
    return request.app.state.services.executor.report(task_id, body, request.state.trace_id)


@router.post(
    "/tasks/{task_id}/thumbnails",
    status_code=201,
    responses={
        409: {"description": "租约不匹配"},
        413: {"description": "缩略图超过 300 KB"},
        415: {"description": "文件须为 JPEG"},
    },
)
def upload_thumbnail(
    task_id: str,
    request: Request,
    worker_id: Annotated[str, Form(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")],
    file: Annotated[UploadFile, File(description="JPEG 缩略图，每张最多 300 KB")],
    attempt_count: Annotated[int | None, Form(ge=1)] = None,
    artifact_sha256: Annotated[Sha256 | None, Form()] = None,
) -> ThumbnailRecord:
    jpeg = file.file.read(THUMBNAIL_LIMIT + 1)
    validate_thumbnail(jpeg)
    body = ExecutorReport(worker_id=worker_id, attempt_count=attempt_count)
    return request.app.state.services.executor.upload(
        task_id,
        body,
        jpeg,
        artifact_sha256,
        request.state.trace_id,
    )


@router.get("/tasks/{task_id}/thumbnails/{thumbnail_id}")
def thumbnail(task_id: str, thumbnail_id: str, request: Request) -> ThumbnailContent:
    return request.app.state.services.executor.thumbnail(task_id, thumbnail_id)


@router.get("/tasks/{task_id}/artifacts")
def artifacts(task_id: str, request: Request) -> ArtifactList:
    return request.app.state.services.executor.artifacts(task_id)


@router.post("/artifacts/{artifact_id}/decision")
def decide(artifact_id: str, body: ArtifactDecision, request: Request) -> ReviewedArtifact:
    return request.app.state.services.executor.decide(artifact_id, body, request.state.trace_id)
