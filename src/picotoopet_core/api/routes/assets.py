"""Authenticated trusted-asset registry routes (C006B1). No binary upload endpoint exists."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from picotoopet_core.api.errors import ApiError
from picotoopet_core.assets.models import (
    ScopeKind,
    TrustedAssetRecordV1,
    TrustedAssetRegisterRequestV1,
)
from picotoopet_core.assets.service import (
    FACT_CONFLICT,
    IDEMPOTENCY_CONFLICT,
    NOT_FOUND,
    SCOPE_NOT_FOUND,
    TrustedAssetError,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])

_STATUS = {
    SCOPE_NOT_FOUND: 404,
    NOT_FOUND: 404,
    IDEMPOTENCY_CONFLICT: 409,
    FACT_CONFLICT: 409,
}


def _run(operation):  # type: ignore[no-untyped-def]
    try:
        return operation()
    except TrustedAssetError as error:
        raise ApiError(
            status_code=_STATUS.get(error.code, 409),
            code=error.code,
            message="Trusted asset request cannot be satisfied.",
            retryable=False,
        ) from None


@router.post("/assets", response_model=TrustedAssetRecordV1)
def register_asset(
    payload: TrustedAssetRegisterRequestV1, request: Request
) -> TrustedAssetRecordV1:
    return _run(lambda: request.app.state.services.assets.register(payload))


@router.get("/assets", response_model=list[TrustedAssetRecordV1])
def list_assets(
    request: Request,
    scope_kind: ScopeKind,
    scope_id: str = Query(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$"),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[TrustedAssetRecordV1]:
    return _run(lambda: request.app.state.services.assets.list(scope_kind, scope_id, limit))


@router.get("/assets/{asset_id}", response_model=TrustedAssetRecordV1)
def get_asset(
    asset_id: str,
    request: Request,
    scope_kind: ScopeKind | None = None,
    scope_id: str | None = Query(
        default=None, min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$"
    ),
) -> TrustedAssetRecordV1:
    if (scope_kind is None) != (scope_id is None):
        raise ApiError(
            status_code=422,
            code="TRUSTED_ASSET_SCOPE_INCOMPLETE",
            message="scope_kind and scope_id must be supplied together.",
            retryable=False,
        )
    return _run(
        lambda: request.app.state.services.assets.get(
            asset_id, scope_kind=scope_kind, scope_id=scope_id
        )
    )
