"""Paired device + independent Worker HMAC for a held Episode; never releases GPU."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from picotoopet_core.api.errors import ApiError
from picotoopet_core.api.routes.frame_transfers import _require_secure_delivery_peer
from picotoopet_core.domain.storypack_master_evidence import MasterEvidenceError
from picotoopet_core.domain.storypack_worker_local_proof import (
    WorkerProofError, WorkerProofRegistry,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])
_SHA = r"^[0-9a-f]{64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkerProofClaim(_Strict):
    worker_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")


class WorkerProofSubmit(_Strict):
    contract: str = Field(pattern=r"^picotoo.worker-local-sha-proof.v1$")
    nonce: str = Field(min_length=40, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    worker_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    episode_id: str = Field(min_length=1, max_length=100)
    frozen_plan_sha256: str = Field(pattern=_SHA)
    source_bindings_sha256: str = Field(pattern=_SHA)
    bindings_sha256: str = Field(pattern=_SHA)
    signature: str = Field(pattern=_SHA)


def _require_hold(request: Request) -> WorkerProofRegistry:
    _require_secure_delivery_peer(request)
    if not request.app.state.services.owner_mode_gpu_hold:
        raise ApiError(
            status_code=409, code="WORKER_PROOF_OWNER_HOLD_REQUIRED",
            message="只能在受保护的 Owner HOLD 下证明已冻结素材。",
            retryable=False,
        )
    return request.app.state.worker_proofs


def _deny(error: WorkerProofError | MasterEvidenceError) -> None:
    raise ApiError(
        status_code=409, code=error.code,
        message="Worker 证据与当前冻结计划或真实素材不符，继续保持 GPU HOLD。",
        retryable=False,
    ) from error


@router.post(
    "/studio/worker-proof/claim",
    response_model=None,  # 路由明确返回结构化数据或 HTTP 204，不生成 Union 模型。
    responses={204: {"description": "未启用或暂无待核验的冻结素材"}},
)
async def claim_worker_sha_challenge(
    request: Request, body: WorkerProofClaim,
) -> dict | Response:
    """No unsigned client-supplied paths, task payloads or GPU capability."""
    registry = _require_hold(request)
    try:
        result = await run_in_threadpool(registry.claim, body.worker_id)
    except (WorkerProofError, MasterEvidenceError) as error:
        _deny(error)
    return result if result is not None else Response(status_code=204)


@router.post("/studio/worker-proof/submit")
async def submit_worker_sha_proof(
    request: Request, body: WorkerProofSubmit,
) -> dict:
    """Consume one challenge, verify separate HMAC and Core frozen source hashes."""
    registry = _require_hold(request)
    try:
        return await run_in_threadpool(registry.submit, body.model_dump(mode="json"))
    except (WorkerProofError, MasterEvidenceError) as error:
        _deny(error)
