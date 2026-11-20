"""Loopback-only independent MASTER source review; never issues GPU permission."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from picotoopet_core.api.errors import ApiError
from picotoopet_core.api.routes.studio_owner_review import _Strict, _read
from picotoopet_core.domain.storypack_master_evidence import (
    MasterEvidenceClaim, MasterEvidenceError, MasterEvidenceService,
)
from picotoopet_core.security.owner_auth import require_owner_principal
from picotoopet_core.security.owner_principal import OwnerAuthFailure, OwnerPrincipal

router = APIRouter()
MasterIdentity = Annotated[OwnerPrincipal, Depends(require_owner_principal)]
_SHA = r"^[0-9a-f]{64}$"


class MasterReviewBody(_Strict):
    episode_id: str = Field(min_length=1, max_length=100)
    frozen_plan_sha256: str = Field(pattern=_SHA)
    source_bindings_sha256: str = Field(pattern=_SHA)
    claims: list[MasterEvidenceClaim] = Field(min_length=1, max_length=64)
    confirm_independent_human_review: Literal[True]


class MasterVerifyBody(MasterReviewBody):
    master_review_id: str = Field(min_length=1, max_length=100)


class MasterRevokeBody(_Strict):
    episode_id: str = Field(min_length=1, max_length=100)
    master_review_id: str = Field(min_length=1, max_length=100)


def _service(request: Request) -> MasterEvidenceService:
    services = request.app.state.services
    if not services.owner_mode_gpu_hold:
        raise ApiError(
            status_code=409, code="MASTER_OWNER_HOLD_NOT_ENABLED",
            message="仅能审查已冻结且处于 Owner HOLD 的生产任务。",
            retryable=False,
        )
    return MasterEvidenceService(services.database, services.settings.paths.objects_dir)


def _error(error: MasterEvidenceError | OwnerAuthFailure) -> None:
    raise ApiError(
        status_code=error.status_code if isinstance(error, OwnerAuthFailure) else 409,
        code=error.code,
        message="独立 MASTER 审核未能验证对应冻结任务和真实素材来源。",
        retryable=False,
    ) from error


@router.post("/studio/storypacks/master-review/commit")
async def commit_master_review(request: Request, reviewer: MasterIdentity) -> dict:
    body = await _read(request, MasterReviewBody)
    try:
        return await run_in_threadpool(
            _service(request).commit, episode_id=body.episode_id,
            plan_sha=body.frozen_plan_sha256,
            source_sha=body.source_bindings_sha256,
            principal=reviewer, claims=body.claims,
        )
    except (MasterEvidenceError, OwnerAuthFailure) as error:
        _error(error)


@router.post("/studio/storypacks/master-review/verify")
async def verify_master_review(request: Request, reviewer: MasterIdentity) -> dict:
    body = await _read(request, MasterVerifyBody)
    try:
        return await run_in_threadpool(
            _service(request).verify, review_id=body.master_review_id,
            episode_id=body.episode_id, plan_sha=body.frozen_plan_sha256,
            source_sha=body.source_bindings_sha256,
            principal=reviewer, claims=body.claims,
        )
    except (MasterEvidenceError, OwnerAuthFailure) as error:
        _error(error)


@router.post("/studio/storypacks/master-review/revoke")
async def revoke_master_review(request: Request, reviewer: MasterIdentity) -> dict:
    body = await _read(request, MasterRevokeBody)
    try:
        return await run_in_threadpool(
            _service(request).revoke, review_id=body.master_review_id,
            episode_id=body.episode_id, principal=reviewer,
        )
    except (MasterEvidenceError, OwnerAuthFailure) as error:
        _error(error)
