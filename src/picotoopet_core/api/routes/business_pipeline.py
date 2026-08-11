"""Authenticated REST routes for the 2.3.21.1 end-to-end business pipeline."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from picotoopet_core.api.errors import ApiError
from picotoopet_core.business_pipeline.models import (
    BusinessPipelineRunCreateRequest,
    BusinessPipelineRunRecord,
    BusinessReturnPackageRecord,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/business-pipeline/runs", response_model=BusinessPipelineRunRecord)
def create_pipeline_run(
    payload: BusinessPipelineRunCreateRequest,
    request: Request,
) -> BusinessPipelineRunRecord:
    return execute_pipeline(
        lambda: request.app.state.services.business_pipeline.create_run(
            work_package_id=payload.work_package_id,
            adapter_profile=payload.adapter_profile,
            idempotency_key=payload.idempotency_key,
        )
    )


@router.get("/business-pipeline/runs", response_model=list[BusinessPipelineRunRecord])
def list_pipeline_runs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=200),
) -> list[BusinessPipelineRunRecord]:
    return request.app.state.services.business_pipeline.list_runs(limit=limit)


@router.get("/business-pipeline/runs/{pipeline_run_id}", response_model=BusinessPipelineRunRecord)
def get_pipeline_run(pipeline_run_id: str, request: Request) -> BusinessPipelineRunRecord:
    return execute_pipeline(lambda: request.app.state.services.business_pipeline.get_run(pipeline_run_id))


@router.post("/business-pipeline/runs/{pipeline_run_id}/reconcile", response_model=BusinessPipelineRunRecord)
async def reconcile_pipeline_run(pipeline_run_id: str, request: Request) -> BusinessPipelineRunRecord:
    if await request.body():
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Business pipeline reconcile does not accept a request body.",
            retryable=False,
        )
    return execute_pipeline(lambda: request.app.state.services.business_pipeline.reconcile(pipeline_run_id))


@router.post("/business-pipeline/runs/{pipeline_run_id}/cancel", response_model=BusinessPipelineRunRecord)
async def cancel_pipeline_run(pipeline_run_id: str, request: Request) -> BusinessPipelineRunRecord:
    if await request.body():
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Business pipeline cancel does not accept a request body.",
            retryable=False,
        )
    return execute_pipeline(lambda: request.app.state.services.business_pipeline.cancel(pipeline_run_id))


@router.get(
    "/business-pipeline/runs/{pipeline_run_id}/return-package",
    response_model=BusinessReturnPackageRecord | None,
)
def get_return_package(
    pipeline_run_id: str,
    request: Request,
) -> BusinessReturnPackageRecord | None:
    # ── Metadata is Core-authored; producer cannot restate package paths ─────
    return execute_pipeline(lambda: request.app.state.services.business_pipeline.get_return_package(pipeline_run_id))


@router.get("/business-pipeline/runs/{pipeline_run_id}/return-package/archive")
def download_return_package(pipeline_run_id: str, request: Request) -> FileResponse:
    path = execute_pipeline(
        lambda: request.app.state.services.business_pipeline.return_package_archive(pipeline_run_id)
    )
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"{pipeline_run_id}-business-return-package.zip",
    )


def execute_pipeline[TResult](operation: Callable[[], TResult]) -> TResult:
    try:
        return operation()
    except KeyError as error:
        raise ApiError(
            status_code=404,
            code="BUSINESS_PIPELINE_RESOURCE_NOT_FOUND",
            message="Business pipeline resource not found.",
            retryable=False,
        ) from error
    except ValueError as error:
        raise ApiError(
            status_code=409,
            code=str(error) or "BUSINESS_PIPELINE_STATE_CONFLICT",
            message="Business pipeline state conflicts with the requested operation.",
            retryable=False,
        ) from error
