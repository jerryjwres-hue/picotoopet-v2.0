"""Authenticated bounded Business Automation REST routes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.api.errors import ApiError
from picotoopet_core.business.models import (
    BusinessResultPackageRecord,
    BusinessUploadSessionRecord,
    DeepAiHandoffRecord,
    WorkPackageManifest,
    WorkPackageRecord,
)
from picotoopet_core.business.upload import BusinessUploadError, CHUNK_SIZE_BYTES
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


class BusinessUploadPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: WorkPackageManifest
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    total_size_bytes: int = Field(ge=1, le=256 * 1024 * 1024)


class BusinessUploadPrepareResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_package: WorkPackageRecord
    upload_session: BusinessUploadSessionRecord


@router.post(
    "/business/work-packages/prepare",
    response_model=BusinessUploadPrepareResponse,
)
def prepare_business_work_package(
    payload: BusinessUploadPrepareRequest,
    request: Request,
) -> BusinessUploadPrepareResponse:
    return execute_business(
        lambda: BusinessUploadPrepareResponse(
            work_package=(
                pair := request.app.state.services.business.prepare_upload(
                    payload.manifest,
                    source_digest=payload.source_digest,
                    total_size_bytes=payload.total_size_bytes,
                )
            )[0],
            upload_session=pair[1],
        )
    )


@router.put(
    "/business/upload-sessions/{upload_session_id}/chunks",
    response_model=BusinessUploadSessionRecord,
)
async def upload_business_chunk(
    upload_session_id: str,
    request: Request,
    offset: int = Query(ge=0),
    chunk_sha256: str = Header(pattern=r"^[0-9a-f]{64}$", alias="X-Chunk-SHA256"),
) -> BusinessUploadSessionRecord:
    body = await request.body()
    if not body or len(body) > CHUNK_SIZE_BYTES:
        raise ApiError(
            status_code=413,
            code="BUSINESS_CHUNK_SIZE_INVALID",
            message="Business upload chunk must be between 1 byte and 4 MiB.",
            retryable=False,
        )
    return execute_business(
        lambda: request.app.state.services.business.write_chunk(
            upload_session_id,
            offset=offset,
            expected_sha256=chunk_sha256,
            payload=body,
        )
    )


@router.post(
    "/business/upload-sessions/{upload_session_id}/finalize",
    response_model=WorkPackageRecord,
)
async def finalize_business_upload(
    upload_session_id: str,
    request: Request,
) -> WorkPackageRecord:
    if await request.body():
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Business upload finalize does not accept a request body.",
            retryable=False,
        )
    return execute_business(
        lambda: request.app.state.services.business.finalize_upload(upload_session_id)
    )


@router.get("/business/work-packages", response_model=list[WorkPackageRecord])
def list_business_work_packages(
    request: Request,
    limit: int = Query(default=100, ge=1, le=200),
) -> list[WorkPackageRecord]:
    return request.app.state.services.business.list_work_packages(limit=limit)


@router.get("/business/work-packages/{work_package_id}", response_model=WorkPackageRecord)
def get_business_work_package(work_package_id: str, request: Request) -> WorkPackageRecord:
    return execute_business(
        lambda: request.app.state.services.business.get_work_package(work_package_id)
    )


@router.post("/business/work-packages/{work_package_id}/cancel", response_model=WorkPackageRecord)
async def cancel_business_work_package(work_package_id: str, request: Request) -> WorkPackageRecord:
    if await request.body():
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Business cancel does not accept a request body.",
            retryable=False,
        )
    return execute_business(lambda: request.app.state.services.business.cancel(work_package_id))


@router.get(
    "/business/work-packages/{work_package_id}/result",
    response_model=BusinessResultPackageRecord | None,
)
def get_business_result(work_package_id: str, request: Request) -> BusinessResultPackageRecord | None:
    return execute_business(lambda: request.app.state.services.business.result_for(work_package_id))


@router.get("/business/work-packages/{work_package_id}/result/download")
def download_business_result(work_package_id: str, request: Request) -> FileResponse:
    path = execute_business(lambda: request.app.state.services.business.result_archive(work_package_id))
    return FileResponse(path, media_type="application/zip", filename=f"{work_package_id}-result.zip")


@router.get(
    "/business/work-packages/{work_package_id}/deep-ai-handoff",
    response_model=DeepAiHandoffRecord | None,
)
def get_business_handoff(work_package_id: str, request: Request) -> DeepAiHandoffRecord | None:
    return execute_business(lambda: request.app.state.services.business.handoff_for(work_package_id))


@router.get("/business/work-packages/{work_package_id}/deep-ai-handoff/download")
def download_business_handoff(work_package_id: str, request: Request) -> FileResponse:
    path = execute_business(lambda: request.app.state.services.business.handoff_archive(work_package_id))
    return FileResponse(path, media_type="application/zip", filename=f"{work_package_id}-deep-ai-handoff.zip")


def execute_business[TResult](operation: Callable[[], TResult]) -> TResult:
    try:
        return operation()
    except KeyError as error:
        raise ApiError(
            status_code=404,
            code="BUSINESS_RESOURCE_NOT_FOUND",
            message="Business automation resource not found.",
            retryable=False,
        ) from error
    except BusinessUploadError as error:
        status = 409 if "CONFLICT" in error.code else 400
        raise ApiError(
            status_code=status,
            code=error.code,
            message="Business Work Package upload was rejected by the bounded contract.",
            retryable=False,
        ) from error
    except ValueError as error:
        raise ApiError(
            status_code=409,
            code="BUSINESS_STATE_CONFLICT",
            message="Business automation state conflicts with the requested operation.",
            retryable=False,
        ) from error
