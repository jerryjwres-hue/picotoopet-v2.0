"""Authenticated bounded Creative Intelligence REST routes."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from picotoopet_core.api.errors import ApiError
from picotoopet_core.creative.models import (
    CreativeDeepAiHandoffRecord,
    CreativeEligibleSourceRecord,
    CreativeJobCreateRequest,
    CreativeJobRecord,
    CreativePackageRecord,
)
from picotoopet_core.creative.source import CreativeSourceError
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/creative/eligible-sources", response_model=list[CreativeEligibleSourceRecord])
def list_eligible_creative_sources(request: Request) -> list[CreativeEligibleSourceRecord]:
    return request.app.state.services.creative.list_eligible_sources()


@router.post("/creative/jobs", response_model=CreativeJobRecord)
def create_creative_job(payload: CreativeJobCreateRequest, request: Request) -> CreativeJobRecord:
    return execute_creative(
        lambda: request.app.state.services.creative.create_job(
            source_result_package_ids=payload.source_result_package_ids,
            creative_profile=payload.creative_profile,
            creative_objective=payload.creative_objective,
            idempotency_key=payload.idempotency_key,
        )
    )


@router.get("/creative/jobs", response_model=list[CreativeJobRecord])
def list_creative_jobs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=200),
) -> list[CreativeJobRecord]:
    return request.app.state.services.creative.list_jobs(limit=limit)


@router.get("/creative/jobs/{creative_job_id}", response_model=CreativeJobRecord)
def get_creative_job(creative_job_id: str, request: Request) -> CreativeJobRecord:
    return execute_creative(lambda: request.app.state.services.creative.get_job(creative_job_id))


@router.post("/creative/jobs/{creative_job_id}/cancel", response_model=CreativeJobRecord)
async def cancel_creative_job(creative_job_id: str, request: Request) -> CreativeJobRecord:
    if await request.body():
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Creative cancel does not accept a request body.",
            retryable=False,
        )
    return execute_creative(lambda: request.app.state.services.creative.cancel(creative_job_id))


@router.get(
    "/creative/jobs/{creative_job_id}/package",
    response_model=CreativePackageRecord | None,
)
def get_creative_package(creative_job_id: str, request: Request) -> CreativePackageRecord | None:
    return execute_creative(lambda: request.app.state.services.creative.get_package(creative_job_id))


@router.get("/creative/jobs/{creative_job_id}/package/download")
def download_creative_package(creative_job_id: str, request: Request) -> FileResponse:
    path = execute_creative(lambda: request.app.state.services.creative.package_archive(creative_job_id))
    return FileResponse(path, media_type="application/zip", filename=f"{creative_job_id}-creative-package.zip")


@router.get(
    "/creative/jobs/{creative_job_id}/deep-ai-handoff",
    response_model=CreativeDeepAiHandoffRecord | None,
)
def get_creative_handoff(creative_job_id: str, request: Request) -> CreativeDeepAiHandoffRecord | None:
    return execute_creative(lambda: request.app.state.services.creative.get_handoff(creative_job_id))


@router.get("/creative/jobs/{creative_job_id}/deep-ai-handoff/download")
def download_creative_handoff(creative_job_id: str, request: Request) -> FileResponse:
    path = execute_creative(lambda: request.app.state.services.creative.handoff_archive(creative_job_id))
    return FileResponse(path, media_type="application/zip", filename=f"{creative_job_id}-creative-handoff.zip")


def execute_creative[TResult](operation: Callable[[], TResult]) -> TResult:
    try:
        return operation()
    except KeyError as error:
        raise ApiError(
            status_code=404,
            code="CREATIVE_RESOURCE_NOT_FOUND",
            message="Creative Intelligence resource not found.",
            retryable=False,
        ) from error
    except CreativeSourceError as error:
        raise ApiError(
            status_code=409,
            code=error.code,
            message="Creative source set was rejected by the closed provenance contract.",
            retryable=False,
        ) from error
    except ValueError as error:
        raise ApiError(
            status_code=409,
            code="CREATIVE_STATE_CONFLICT",
            message="Creative Intelligence state conflicts with the requested operation.",
            retryable=False,
        ) from error
