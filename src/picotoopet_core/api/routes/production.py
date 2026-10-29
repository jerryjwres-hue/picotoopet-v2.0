"""Authenticated REST routes for the closed 2.3.20.1 production plane."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from fastapi.responses import FileResponse

from picotoopet_core.api.errors import ApiError
from picotoopet_core.production.models import (
    ProductionClaimRecord,
    ProductionClaimRequest,
    ProductionEligibleCreativeRecord,
    ProductionHeartbeatRequest,
    ProductionJobCreateRequest,
    ProductionJobRecord,
    ProductionPackageRecord,
    ProductionPlan,
    ProductionTaskAttemptRequest,
    ProductionTaskCommitRequest,
    ProductionTaskFailureRequest,
    ProductionTaskRecord,
)
from picotoopet_core.production.versioned_plan import (
    ApprovedReferenceAuthorizationV11, ProductionJobCreateV11Request, ProductionPlanV11,
    WorkerWitnessV11,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/production/eligible", response_model=list[ProductionEligibleCreativeRecord])
def list_eligible_production_sources(request: Request) -> list[ProductionEligibleCreativeRecord]:
    # ── Eligibility is derived only from Core-stored creative facts ─────────
    return request.app.state.services.production.list_eligible()


@router.post("/production/jobs", response_model=ProductionJobRecord)
def create_production_job(payload: ProductionJobCreateRequest, request: Request) -> ProductionJobRecord:
    return execute_production(lambda: request.app.state.services.production.create_job(payload))


@router.post("/production/jobs/v1.1", response_model=ProductionJobRecord)
def create_production_job_v11(
    payload: ProductionJobCreateV11Request, request: Request
) -> ProductionJobRecord:
    # Only explicitly selected, already Approved Core reference scopes are used.
    return execute_production(lambda: request.app.state.services.production.create_job_v11(payload))


@router.get("/production/jobs", response_model=list[ProductionJobRecord])
def list_production_jobs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=200),
) -> list[ProductionJobRecord]:
    return request.app.state.services.production.list_jobs(limit=limit)


@router.get("/production/jobs/{production_job_id}", response_model=ProductionJobRecord)
def get_production_job(production_job_id: str, request: Request) -> ProductionJobRecord:
    return execute_production(lambda: request.app.state.services.production.get_job(production_job_id))


@router.get("/production/jobs/{production_job_id}/plan", response_model=ProductionPlan | ProductionPlanV11)
def get_production_plan(production_job_id: str, request: Request) -> ProductionPlan | ProductionPlanV11:
    return execute_production(lambda: request.app.state.services.production.get_plan(production_job_id))


@router.get(
    "/production/jobs/{production_job_id}/tasks/{production_task_id}/reference-authorization",
    response_model=ApprovedReferenceAuthorizationV11,
)
def authorize_production_reference_v11(
    production_job_id: str,
    production_task_id: str,
    request: Request,
) -> ApprovedReferenceAuthorizationV11:
    return execute_production(lambda: request.app.state.services.production.authorize_reference_v11(
        production_job_id, production_task_id
    ))


class WorkerChallengeRequestV11(BaseModel):
    """Scoped transport request. Bearer alone is NOT proof of a Worker identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    worker_key_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    executor_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class WorkerChallengeResponseV11(BaseModel):
    """One-time challenge, NOT approval, lease, executable attestation, or token."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["production.worker_challenge.v1"] = "production.worker_challenge.v1"
    worker_key_id: str
    executor_id: str
    production_job_id: str
    plan_digest: str
    nonce: str = Field(pattern=r"^[0-9a-f]{64}$")
    issued_at: datetime
    expires_at: datetime


@router.post(
    "/production/jobs/{production_job_id}/worker-challenge",
    response_model=WorkerChallengeResponseV11,
)
def issue_worker_challenge_v11(
    production_job_id: str,
    payload: WorkerChallengeRequestV11,
    request: Request,
    response: Response,
) -> WorkerChallengeResponseV11:
    # ── Existing require_auth is transport-only; never key enrollment, trust
    # ── elevation, lease allocation, or permission to issue a GPU/Comfy POST.
    # ── No GET, URL nonce or cacheable challenge. Key lookup and approval are
    # ── Core DB facts checked atomically with the new random nonce insertion.
    nonce, issued_at, expires_at = execute_production(
        lambda: request.app.state.services.production.issue_worker_challenge_v11(
            production_job_id, payload.worker_key_id, payload.executor_id, payload.plan_digest
        )
    )
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    return WorkerChallengeResponseV11(
        worker_key_id=payload.worker_key_id,
        executor_id=payload.executor_id,
        production_job_id=production_job_id,
        plan_digest=payload.plan_digest,
        nonce=nonce,
        issued_at=issued_at,
        expires_at=expires_at,
    )


@router.post("/production/jobs/{production_job_id}/witness/preflight", status_code=204)
def preflight_production_worker_witness_v11(
    production_job_id: str,
    payload: WorkerWitnessV11,
    request: Request,
) -> None:
    # ── Strict proposal intake only, NOT a Claim or a Worker trust enrollment.
    # ── An ordinary UI bearer is insufficient: until a separately pinned,
    # ── revocable same-EXE key + durable nonce/Windows snapshot proof exists,
    # ── every request must return 409, never a 204 production admission.
    return execute_production(
        lambda: request.app.state.services.production.inspect_worker_witness_v11(
            production_job_id, payload
        )
    )


@router.post("/production/jobs/{production_job_id}/claim", response_model=ProductionClaimRecord)
def claim_production_job(
    production_job_id: str,
    payload: ProductionClaimRequest,
    request: Request,
) -> ProductionClaimRecord:
    return execute_production(
        lambda: request.app.state.services.production.claim(production_job_id, payload.executor_id)
    )


@router.post("/production/jobs/{production_job_id}/heartbeat", response_model=ProductionJobRecord)
def heartbeat_production_job(
    production_job_id: str,
    payload: ProductionHeartbeatRequest,
    request: Request,
) -> ProductionJobRecord:
    return execute_production(
        lambda: request.app.state.services.production.heartbeat(production_job_id, payload)
    )


@router.post(
    "/production/jobs/{production_job_id}/tasks/{production_task_id}/attempt",
    response_model=ProductionTaskRecord,
)
def mark_production_attempt(
    production_job_id: str,
    production_task_id: str,
    payload: ProductionTaskAttemptRequest,
    request: Request,
) -> ProductionTaskRecord:
    return execute_production(
        lambda: request.app.state.services.production.mark_attempt(
            production_job_id,
            production_task_id,
            payload,
        )
    )


@router.post(
    "/production/jobs/{production_job_id}/tasks/{production_task_id}/failure",
    response_model=ProductionTaskRecord,
)
def fail_production_task(
    production_job_id: str,
    production_task_id: str,
    payload: ProductionTaskFailureRequest,
    request: Request,
) -> ProductionTaskRecord:
    # ── Renderer failure is an explicit bounded write, never a cancel alias ─
    return execute_production(
        lambda: request.app.state.services.production.fail_task(
            production_job_id,
            production_task_id,
            payload,
        )
    )


@router.post(
    "/production/jobs/{production_job_id}/tasks/{production_task_id}/result",
    response_model=ProductionTaskRecord,
)
def commit_production_result(
    production_job_id: str,
    production_task_id: str,
    payload: ProductionTaskCommitRequest,
    request: Request,
) -> ProductionTaskRecord:
    return execute_production(
        lambda: request.app.state.services.production.commit_task(
            production_job_id,
            production_task_id,
            payload,
        )
    )


@router.post("/production/jobs/{production_job_id}/cancel", response_model=ProductionJobRecord)
async def cancel_production_job(production_job_id: str, request: Request) -> ProductionJobRecord:
    # ── Cancellation has no mutable execution payload ───────────────────────
    if await request.body():
        raise ApiError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Production cancel does not accept a request body.",
            retryable=False,
        )
    return execute_production(lambda: request.app.state.services.production.cancel(production_job_id))


@router.get(
    "/production/jobs/{production_job_id}/package",
    response_model=ProductionPackageRecord | None,
)
def get_production_package(
    production_job_id: str,
    request: Request,
) -> ProductionPackageRecord | None:
    return execute_production(lambda: request.app.state.services.production.get_package(production_job_id))


@router.get("/production/jobs/{production_job_id}/package/download")
def download_production_package(production_job_id: str, request: Request) -> FileResponse:
    path = execute_production(lambda: request.app.state.services.production.package_archive(production_job_id))
    return FileResponse(path, media_type="application/zip", filename=f"{production_job_id}-production-package.zip")


def execute_production[TResult](operation: Callable[[], TResult]) -> TResult:
    # ── Closed error translation keeps internal state details private ───────
    try:
        return operation()
    except KeyError as error:
        raise ApiError(
            status_code=404,
            code="PRODUCTION_RESOURCE_NOT_FOUND",
            message="Production resource not found.",
            retryable=False,
        ) from error
    except ValueError as error:
        raise ApiError(
            status_code=409,
            code=str(error) or "PRODUCTION_STATE_CONFLICT",
            message="Production state conflicts with the requested operation.",
            retryable=False,
        ) from error
