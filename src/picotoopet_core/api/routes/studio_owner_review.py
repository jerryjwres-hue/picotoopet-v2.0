"""Loopback-only, scoped Owner storyboard review; never operates the GPU queue."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from picotoopet_core.api.errors import ApiError
from picotoopet_core.domain.storypack import StoryPackV1, _unique_json_pairs
from picotoopet_core.domain.storypack_asset_use import (
    AssetUseAttestationService,
    AssetUseClaim,
    AssetUseError,
)
from picotoopet_core.domain.storypack_owner_commit import (
    StoryboardReviewError,
    StoryboardReviewService,
)
from picotoopet_core.security.owner_auth import require_owner_principal
from picotoopet_core.security.owner_principal import (
    OwnerAuthFailure,
    OwnerPrincipal,
    require_owner_scope,
)

router = APIRouter()
OwnerIdentity = Annotated[OwnerPrincipal, Depends(require_owner_principal)]
_SUBJECT_PATTERN = r"^pet:[a-z0-9][a-z0-9-]{1,63}$"
_HASH_PATTERN = r"^[0-9a-f]{64}$"
_MAX_BODY_BYTES = 160 * 1024


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StoryboardPreviewBody(_Strict):
    subject_key: str = Field(pattern=_SUBJECT_PATTERN)
    storypack: dict[str, Any]


class StoryboardCommitBody(StoryboardPreviewBody):
    expected_subject_sha256: str = Field(pattern=_HASH_PATTERN)
    expires_seconds: int = Field(default=900, ge=60, le=3600)


class StoryboardVerifyBody(StoryboardPreviewBody):
    review_id: str = Field(min_length=1, max_length=100)


class StoryboardRevokeBody(_Strict):
    subject_key: str = Field(pattern=_SUBJECT_PATTERN)
    review_id: str = Field(min_length=1, max_length=100)


async def _read(request: Request, body_type: type[_Strict]) -> _Strict:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise ApiError(
            status_code=415, code="VALIDATION_ERROR",
            message="Owner 故事审核仅接受 JSON。", retryable=False,
        )
    payload = bytearray()
    async for chunk in request.stream():
        if len(payload) + len(chunk) > _MAX_BODY_BYTES:
            raise ApiError(
                status_code=413, code="VALIDATION_ERROR",
                message="Owner 故事审核正文超过限制。", retryable=False,
            )
        payload.extend(chunk)
    try:
        raw = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unique_json_pairs)
        return body_type.model_validate(raw)
    except (UnicodeError, ValueError, TypeError, ValidationError, RecursionError) as exc:
        # 不在客户端错误中回显私密剧本内容或提交的 Bearer 凭据。
        raise ApiError(
            status_code=422, code="VALIDATION_ERROR",
            message="Owner 故事审核结构或字段无效。", retryable=False,
        ) from exc


def _authorize(principal: OwnerPrincipal, subject_key: str) -> None:
    try:
        # 明确区分 #244 的 owner_facts.review 与动态分镜 storypack.review。
        require_owner_scope(principal, subject_key, permission="storypack.review")
    except OwnerAuthFailure as exc:
        raise ApiError(
            status_code=exc.status_code, code=exc.code,
            message="当前 Owner 凭据无此主体的分镜审核权限。", retryable=False,
        ) from exc


def _service(request: Request) -> StoryboardReviewService:
    services = request.app.state.services
    return StoryboardReviewService(services.database, services.settings.paths.objects_dir)


def _pack(body: StoryboardPreviewBody) -> StoryPackV1:
    try:
        return StoryPackV1.model_validate(body.storypack)
    except ValidationError as exc:
        raise ApiError(
            status_code=422, code="VALIDATION_ERROR",
            message="StoryPack 格式或连续性校验不通过。", retryable=False,
        ) from exc


def _error(exc: StoryboardReviewError) -> None:
    raise ApiError(
        status_code=409, code=exc.code,
        message="Owner 审核证据失效或发生冲突。", retryable=False,
    ) from exc


@router.post("/studio/storypacks/owner-review/preview")
async def preview_storyboard(request: Request, principal: OwnerIdentity) -> dict:
    """Prepare verified content hashes, not an approval or production authority."""
    body = await _read(request, StoryboardPreviewBody)
    _authorize(principal, body.subject_key)
    result = _service(request).subject(_pack(body))
    return {
        "subject_key": body.subject_key,
        "review_actor_id": principal.actor_id,
        "storypack_sha256": result["storypack_sha256"],
        "review": result["review"],
        "can_queue": False,
        "gpu_authorized": False,
    }


@router.post("/studio/storypacks/owner-review/commit")
async def commit_storyboard(
    request: Request, principal: OwnerIdentity,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=10, max_length=200),
) -> dict:
    """Commit a fresh, scoped storyboard-only decision to Core's audit ledger."""
    body = await _read(request, StoryboardCommitBody)
    _authorize(principal, body.subject_key)
    try:
        return _service(request).commit(
            pack=_pack(body), subject_key=body.subject_key, principal=principal,
            expected_subject_sha256=body.expected_subject_sha256,
            idempotency_key=idempotency_key, expires_seconds=body.expires_seconds,
        )
    except StoryboardReviewError as exc:
        _error(exc)


@router.post("/studio/storypacks/owner-review/verify")
async def verify_storyboard(request: Request, principal: OwnerIdentity) -> dict:
    """Freshly rehash all managed bytes; never authorize episode creation."""
    body = await _read(request, StoryboardVerifyBody)
    _authorize(principal, body.subject_key)
    try:
        return _service(request).verify(
            pack=_pack(body), subject_key=body.subject_key,
            review_id=body.review_id, principal=principal,
        )
    except StoryboardReviewError as exc:
        _error(exc)


@router.post("/studio/storypacks/owner-review/revoke")
async def revoke_storyboard(request: Request, principal: OwnerIdentity) -> dict:
    """Append a revocation that prevents subsequent storyboard review reuse."""
    body = await _read(request, StoryboardRevokeBody)
    _authorize(principal, body.subject_key)
    try:
        return _service(request).revoke(
            subject_key=body.subject_key, review_id=body.review_id, principal=principal,
        )
    except StoryboardReviewError as exc:
        _error(exc)


class AssetUsePreviewBody(StoryboardPreviewBody):
    """Per-asset rights statements are explicit, not inferred from DB existence."""

    claims: list[AssetUseClaim] = Field(min_length=1, max_length=64)


class AssetUseCommitBody(AssetUsePreviewBody):
    expected_attestation_sha256: str = Field(pattern=_HASH_PATTERN)
    expires_seconds: int = Field(default=900, ge=60, le=3600)


class AssetUseVerifyBody(AssetUsePreviewBody):
    attestation_id: str = Field(min_length=1, max_length=100)


class AssetUseRevokeBody(_Strict):
    subject_key: str = Field(pattern=_SUBJECT_PATTERN)
    attestation_id: str = Field(min_length=1, max_length=100)


def _authorize_asset_use(principal: OwnerPrincipal, subject_key: str) -> None:
    try:
        # 单独的 asset_use.attest Scope，不继承 storypack.review 或设备 Bearer。
        require_owner_scope(principal, subject_key, permission="asset_use.attest")
    except OwnerAuthFailure as exc:
        raise ApiError(
            status_code=exc.status_code,
            code=exc.code,
            message="当前 Owner 凭据无此主体的素材使用权声明权限。",
            retryable=False,
        ) from exc


def _asset_use(request: Request) -> AssetUseAttestationService:
    services = request.app.state.services
    return AssetUseAttestationService(
        services.database, services.settings.paths.objects_dir
    )


def _asset_error(error: AssetUseError) -> None:
    # 对外只返回稳定原因码，不回显私有许可证内容或本地素材路径。
    raise ApiError(
        status_code=409, code=error.code,
        message="素材使用声明与最新文件或 Owner 证据不一致。",
        retryable=False,
    ) from error


@router.post("/studio/storypacks/owner-review/asset-use/preview")
async def preview_asset_use(request: Request, principal: OwnerIdentity) -> dict:
    body = await _read(request, AssetUsePreviewBody)
    _authorize_asset_use(principal, body.subject_key)
    try:
        return _asset_use(request).prepare(_pack(body), body.claims)
    except AssetUseError as exc:
        _asset_error(exc)


@router.post("/studio/storypacks/owner-review/asset-use/commit")
async def commit_asset_use(
    request: Request, principal: OwnerIdentity,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=10, max_length=200),
) -> dict:
    body = await _read(request, AssetUseCommitBody)
    _authorize_asset_use(principal, body.subject_key)
    try:
        return _asset_use(request).commit(
            pack=_pack(body), claims=body.claims, subject_key=body.subject_key,
            principal=principal,
            expected_attestation_sha256=body.expected_attestation_sha256,
            idempotency_key=idempotency_key, expires_seconds=body.expires_seconds,
        )
    except AssetUseError as exc:
        _asset_error(exc)


@router.post("/studio/storypacks/owner-review/asset-use/verify")
async def verify_asset_use(request: Request, principal: OwnerIdentity) -> dict:
    body = await _read(request, AssetUseVerifyBody)
    _authorize_asset_use(principal, body.subject_key)
    try:
        return _asset_use(request).verify(
            pack=_pack(body), claims=body.claims, subject_key=body.subject_key,
            principal=principal, attestation_id=body.attestation_id,
        )
    except AssetUseError as exc:
        _asset_error(exc)


@router.post("/studio/storypacks/owner-review/asset-use/revoke")
async def revoke_asset_use(request: Request, principal: OwnerIdentity) -> dict:
    body = await _read(request, AssetUseRevokeBody)
    _authorize_asset_use(principal, body.subject_key)
    try:
        return _asset_use(request).revoke(
            subject_key=body.subject_key,
            attestation_id=body.attestation_id,
            principal=principal,
        )
    except AssetUseError as exc:
        _asset_error(exc)
