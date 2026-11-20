"""Owner loopback admission and signed per-task challenge on the existing Worker lease API."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from picotoopet_core.api.errors import ApiError
from picotoopet_core.api.routes.frame_transfers import _require_secure_delivery_peer
from picotoopet_core.api.routes.studio_owner_review import _read
from picotoopet_core.domain.executor import ExecutorLease
from picotoopet_core.domain.storypack_gpu_admission import (
    AdmissionError, ScopedProductionAdmission,
)
from picotoopet_core.domain.storypack_master_evidence import MasterEvidenceError
from picotoopet_core.domain.storypack_worker_local_proof import WorkerProofError
from picotoopet_core.security.auth import require_auth
from picotoopet_core.security.owner_auth import require_owner_principal
from picotoopet_core.security.owner_principal import OwnerAuthFailure, OwnerPrincipal

router = APIRouter()
_SHA = r"^[0-9a-f]{64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScopedAdmissionBody(_Strict):
    episode_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    frozen_plan_sha256: str = Field(pattern=_SHA)
    master_review_id: str = Field(min_length=1, max_length=100)
    confirm_one_frozen_episode_gpu_admission: Literal[True]


class ScopedRevokeBody(_Strict):
    episode_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    admission_id: str = Field(min_length=1, max_length=100)


def _owner_gate(request: Request) -> ScopedProductionAdmission:
    services = request.app.state.services
    if not services.owner_mode_gpu_hold:
        raise ApiError(
            status_code=409, code="ADMISSION_OWNER_HOLD_REQUIRED",
            message="仅能为受保护的冻结 Episode 做生产准入。",
            retryable=False,
        )
    if not services.settings.scoped_gpu_admission_enabled:
        raise ApiError(
            status_code=409, code="ADMISSION_EXPLICIT_RUNTIME_ENABLE_REQUIRED",
            message="指定 Job 的 GPU 准入仍未通过管理员显式启用。",
            retryable=False,
        )
    return ScopedProductionAdmission(services)


def _blocked(exc: Exception) -> None:
    raise ApiError(
        status_code=exc.status_code if isinstance(exc, OwnerAuthFailure) else 409,
        code=getattr(exc, "code", "ADMISSION_DEPENDENCY_INVALID"),
        message="指定 Episode 的独立来源、Worker 或 Owner 权限当前不满足安全准入。",
        retryable=False,
    ) from exc


@router.post("/studio/storypacks/production-admission/commit")
async def admit_one_production_episode(
    request: Request,
    principal: Annotated[OwnerPrincipal, Depends(require_owner_principal)],
) -> dict:
    body = await _read(request, ScopedAdmissionBody)
    try:
        return await run_in_threadpool(
            _owner_gate(request).admit,
            body.episode_id, body.frozen_plan_sha256, body.master_review_id,
            principal, request.state.trace_id,
        )
    except (AdmissionError, MasterEvidenceError, WorkerProofError, OwnerAuthFailure,
            ValueError, KeyError, TypeError) as error:
        _blocked(error)


@router.post("/studio/storypacks/production-admission/revoke")
async def revoke_one_production_episode(
    request: Request,
    principal: Annotated[OwnerPrincipal, Depends(require_owner_principal)],
) -> dict:
    body = await _read(request, ScopedRevokeBody)
    services = request.app.state.services
    if not services.owner_mode_gpu_hold:
        raise ApiError(
            status_code=409, code="ADMISSION_OWNER_HOLD_REQUIRED",
            message="此部署没有受保护的冻结任务。",
            retryable=False,
        )
    try:
        return await run_in_threadpool(
            ScopedProductionAdmission(services).revoke,
            body.episode_id, body.admission_id, principal, request.state.trace_id,
        )
    except (AdmissionError, MasterEvidenceError, OwnerAuthFailure) as error:
        _blocked(error)


@router.post(
    "/studio/production-admission/lease-challenge",
    response_model=None, responses={204: {"description": "当前无明确授权且可运行的任务"}},
    dependencies=[Depends(require_auth)],
)
async def challenge_exact_task_lease(
    request: Request, body: ExecutorLease,
) -> dict | Response:
    """A paired device may see a nonce; only Worker-HMAC possession can redeem it."""
    _require_secure_delivery_peer(request)
    services = request.app.state.services
    if (not services.owner_mode_gpu_hold
            or not services.settings.scoped_gpu_admission_enabled):
        return Response(status_code=204)
    try:
        offered = await run_in_threadpool(request.app.state.lease_challenges.issue, body)
    except (AdmissionError, MasterEvidenceError, WorkerProofError, ValueError, KeyError):
        return Response(status_code=204)
    return offered if offered is not None else Response(status_code=204)
