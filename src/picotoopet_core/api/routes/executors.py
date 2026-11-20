"""执行器、缩略图和审片 REST 路由。"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Request, Response, UploadFile

from picotoopet_core.api.thumbnails import validate_thumbnail
from picotoopet_core.api.production_admission_hold import (
    storypack_owner_hold,
)
from picotoopet_core.api.errors import ApiError
from picotoopet_core.api.routes.frame_transfers import _require_secure_delivery_peer
from picotoopet_core.domain.storypack_gpu_admission import AdmissionError, ScopedProductionAdmission
from picotoopet_core.domain.storypack_master_evidence import MasterEvidenceError
from picotoopet_core.domain.storypack_worker_local_proof import WorkerProofError
from picotoopet_core.domain.executor import (
    GPU_TAG,
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
def lease(
    body: ExecutorLease,
    request: Request,
    admission_nonce: str | None = Header(default=None, alias="X-Picotoo-Admission-Nonce"),
    admission_hmac: str | None = Header(default=None, alias="X-Picotoo-Admission-HMAC"),
) -> TaskRecord | Response:
    if storypack_owner_hold(request):
        if request.app.state.services.settings.scoped_gpu_admission_enabled:
            _require_secure_delivery_peer(request)
            if admission_nonce and admission_hmac:
                try:
                    # Existing Task/ExecutorService lease tables; one signed exact task only.
                    return request.app.state.lease_challenges.consume(
                        body, admission_nonce, admission_hmac, request.state.trace_id,
                    )
                except (AdmissionError, MasterEvidenceError, WorkerProofError,
                        ValueError, KeyError) as error:
                    raise ApiError(
                        status_code=409,
                        code=getattr(error, "code", "ADMISSION_RECHECK_FAILED"),
                        message="指定任务租约与当前 Owner/MASTER/Worker 证据不一致。",
                        retryable=False,
                    ) from error
        # RUNNING + 同 Worker 仅证明 Core 已发租约，不证明 Windows 已 POST GPU。
        # Owner HOLD 时任何旧 resume 都不能把完整可执行 payload 再发给 Worker。
        # 已提交的 Report 仍可由独立的 complete/fail 入口按原租约验证。
        return Response(status_code=204)
    return request.app.state.services.executor.lease(body, request.state.trace_id) or Response(
        status_code=204,
    )


@router.post("/tasks/{task_id}/heartbeat", responses={409: {"description": "租约不匹配"}})
def heartbeat(task_id: str, body: ExecutorHeartbeat, request: Request) -> TaskRecord:
    if storypack_owner_hold(request):
        if request.app.state.services.settings.scoped_gpu_admission_enabled:
            _require_secure_delivery_peer(request)
            # 撤销与有效租约必须在 GPU 提交前重新确认，拒绝局域网明文。
            if ScopedProductionAdmission(
                request.app.state.services
            ).heartbeat_allowed(task_id, body.worker_id, body.attempt_count):
                return request.app.state.services.executor.heartbeat(
                    task_id, body, request.state.trace_id,
                )
        row = request.app.state.services.database.fetchone(
            "SELECT task_type, resource_tag FROM tasks WHERE task_id = ?",
            (task_id,),
        )
        if row is not None and (
            row["task_type"] in TASK_RUNNERS or row["resource_tag"] == GPU_TAG
        ):
            # 旧 Worker 若已租约但尚未 POST，本次 409 会强制进入 resume。
            # 而 resume 在 Owner HOLD 下为 204，因此不能再提交新 GPU 请求。
            raise ApiError(
                status_code=409,
                code="STORYPACK_PRODUCTION_ADMISSION_REQUIRED",
                message="Owner HOLD 已冻结旧 GPU 租约；只能收集已完成的原始回执。",
                retryable=False,
            )
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
    # 旧审片 redo 会克隆新的 GPU 作业；人工 QC 放行会让下游旧任务重新可租约。
    # 受保护 Owner 模式只允许普通选片/拒绝，不允许借这些按钮绕过冻结 Plan。
    if storypack_owner_hold(request) and (
        body.decision == "redo" or body.accept_qc_failure
    ):
        raise ApiError(
            status_code=409,
            code="STORYPACK_PRODUCTION_ADMISSION_REQUIRED",
            message="请先通过 Owner、MASTER 和冻结 Plan 的正式生产准入。",
            retryable=False,
        )
    return request.app.state.services.executor.decide(artifact_id, body, request.state.trace_id)
