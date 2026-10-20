"""Authenticated reference-image batch registration; never approves silently."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.api.errors import ApiError
from picotoopet_core.approvals.service import ApprovalError
from picotoopet_core.production.reference_registration import (
    ReferenceBatchRequestV1,
    ReferenceBatchReceiptV1,
    ReferenceRegistrationService,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


def _run(action: Callable[[], ReferenceBatchReceiptV1]) -> ReferenceBatchReceiptV1:
    try:
        return action()
    except ApprovalError as error:
        raise ApiError(
            status_code=409, code=str(error), message="Reference authorization rejected.",
            retryable=False,
        ) from error


def _service(request: Request) -> ReferenceRegistrationService:
    services = request.app.state.services
    return ReferenceRegistrationService(services.database, services.approvals, services.creative_store)


@router.post("/production/references/batches", response_model=ReferenceBatchReceiptV1, status_code=201)
def register_reference_batch(
    payload: ReferenceBatchRequestV1,
    request: Request,
    idempotency_key: str = Header(min_length=1, max_length=200, alias="Idempotency-Key"),
) -> ReferenceBatchReceiptV1:
    """Submit exact previewed shot/image scopes for a single PENDING approval.

    The Windows client supplied hash is not falsely asserted to be Mac-observed.
    This does not send to Comfy or enable a Production v1.0 I2V task.
    """
    return _run(lambda: _service(request).register(payload, idempotency_key=idempotency_key))


@router.get("/production/references/batches/{approval_id}", response_model=ReferenceBatchReceiptV1)
def get_reference_batch(approval_id: str, request: Request) -> ReferenceBatchReceiptV1:
    return _run(lambda: _service(request).get(approval_id))


class ReferenceRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=500)


@router.post("/production/references/batches/{approval_id}/revoke", response_model=ReferenceBatchReceiptV1)
def revoke_reference_batch(
    approval_id: str, payload: ReferenceRevokeRequest, request: Request
) -> ReferenceBatchReceiptV1:
    """Explicit authenticated revoke for all shot grants in one previously approved batch."""
    return _run(lambda: _service(request).revoke(
        approval_id, request_digest=payload.request_digest, reason=payload.reason
    ))
