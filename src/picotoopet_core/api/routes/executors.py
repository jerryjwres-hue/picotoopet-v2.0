"""执行器、缩略图和审片 REST 路由。"""

from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from PIL import Image, UnidentifiedImageError

from picotoopet_core.api.errors import ApiError
from picotoopet_core.domain.executor import (
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
THUMBNAIL_LIMIT = 300 * 1024


@router.post(
    "/executors/lease", response_model=TaskRecord, responses={204: {"description": "无任务"}}
)
def lease(body: ExecutorLease, request: Request) -> TaskRecord | Response:
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
    if len(jpeg) > THUMBNAIL_LIMIT:
        raise ApiError(
            status_code=413,
            code="VALIDATION_ERROR",
            message="缩略图不能超过 300 KB。",
            retryable=False,
        )
    try:
        with Image.open(BytesIO(jpeg), formats=["JPEG"]) as image:
            if max(image.size) > 8192:
                raise ValueError("JPEG dimensions")
            image.load()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, ValueError) as exc:
        raise ApiError(
            status_code=415,
            code="VALIDATION_ERROR",
            message="缩略图必须是有效的 JPEG 文件。",
            retryable=False,
        ) from exc
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
