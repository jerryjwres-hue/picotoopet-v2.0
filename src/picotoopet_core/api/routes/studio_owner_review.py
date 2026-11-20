"""Loopback-only, scoped Owner storyboard review; never operates the GPU queue."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from picotoopet_core.api.errors import ApiError
from picotoopet_core.domain.storypack import StoryPackV1, _unique_json_pairs
from picotoopet_core.domain.episode import Episode
from picotoopet_core.domain.storypack_frame_sources import inspect_frame_sources
from picotoopet_core.domain.storypack_frame_bundle import export_frame_bundle
from picotoopet_core.domain.frame_transfer_tickets import FrameTransferError
from starlette.concurrency import run_in_threadpool
from picotoopet_core.domain.storypack_episode_candidate import (
    EpisodeCandidateError,
    complete_storypack_episode_preview,
)
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


class ProductionReadinessBody(AssetUseVerifyBody):
    """One Owner-scoped combined preflight; not a GPU authorization request."""

    storyboard_review_id: str = Field(min_length=1, max_length=100)
    storypack_sha256: str = Field(pattern=_HASH_PATTERN)
    completion: dict[str, Any]


@router.post("/studio/storypacks/owner-review/production-readiness")
async def preview_production_readiness(
    request: Request, principal: OwnerIdentity,
) -> dict:
    """Recheck current independent evidence without creating any production tasks."""
    body = await _read(request, ProductionReadinessBody)
    _authorize(principal, body.subject_key)
    _authorize_asset_use(principal, body.subject_key)
    pack = _pack(body)

    # 每次都重读实际 MANAGED 对象字节与 Owner 审计，不接受客户端传回的 PASS。
    checks: dict[str, bool] = {
        "storyboard_review_current": False,
        "asset_use_attestation_current": False,
        "episode_contract_valid": False,
        "episode_budget_allowed": False,
        "first_frame_mac_content_bound": False,
        "first_frame_worker_local_verified": False,
        "master_rights_independently_verified": False,
        "first_frame_master_approved": False,
        "dynamic_story_policy_admitted": False,
        "gpu_hold_released": False,
    }
    reasons: list[str] = []
    try:
        storyboard = _service(request).verify(
            pack=pack, subject_key=body.subject_key,
            review_id=body.storyboard_review_id, principal=principal,
        )
        checks["storyboard_review_current"] = (
            storyboard["status"] == "STORYBOARD_ONLY_CURRENT"
        )
    except StoryboardReviewError as error:
        reasons.append(error.code)

    try:
        attestation = _asset_use(request).verify(
            pack=pack, claims=body.claims,
            subject_key=body.subject_key, principal=principal,
            attestation_id=body.attestation_id,
        )
        checks["asset_use_attestation_current"] = (
            attestation["status"] == "OWNER_ASSET_USE_CURRENT"
        )
    except AssetUseError as error:
        reasons.append(error.code)

    frame_sources = None
    try:
        candidate = complete_storypack_episode_preview(
            pack, body.storypack_sha256, body.completion,
        )
        checks["episode_contract_valid"] = candidate["episode_contract_valid"]
        compiled_episode = Episode.model_validate(candidate["episode"])
        budget = request.app.state.services.production.preview_budget(compiled_episode)

        # Mac 受管理 ID 不等于 Windows 本机路径；读取当前文件后仍只提供
        # 内容摘要，绝不把无凭据的 LLM 路径注入 Worker/ComfyUI。
        owner_subject = _service(request).subject(pack)["review"]
        frame_sources = inspect_frame_sources(pack, compiled_episode, owner_subject)
        checks["first_frame_mac_content_bound"] = frame_sources[
            "mac_managed_content_verified"
        ]
        checks["first_frame_worker_local_verified"] = frame_sources[
            "worker_local_bytes_verified"
        ]
        reasons.extend(frame_sources["blocking_reasons"])
        checks["episode_budget_allowed"] = budget["allowed"]
        if not budget["allowed"]:
            reasons.append("EPISODE_BUDGET_EXCEEDED")
        episode_sha256 = candidate["candidate_episode_sha256"]
    except (EpisodeCandidateError, ValidationError) as error:
        reasons.append(
            error.code
            if isinstance(error, EpisodeCandidateError)
            else "EPISODE_CONTRACT_INVALID"
        )
        budget = None
        episode_sha256 = None

    # 这些仍须独立、可信的 MASTER/策略/GPU 准入，不能由故事 Owner 声明代替。
    for name, reason in (
        ("master_rights_independently_verified", "MASTER_RIGHTS_NOT_VERIFIED"),
        ("first_frame_master_approved", "FIRST_FRAME_MASTER_NOT_APPROVED"),
        ("dynamic_story_policy_admitted", "DYNAMIC_STORY_POLICY_NOT_ADMITTED"),
        ("gpu_hold_released", "GPU_HOLD_NOT_RELEASED"),
    ):
        if not checks[name]:
            reasons.append(reason)

    return {
        "contract": "picotoo.storypack-production-readiness.v1",
        "status": "BLOCKED_PRODUCTION_ADMISSION",
        "storypack_sha256": body.storypack_sha256,
        "candidate_episode_sha256": episode_sha256,
        "checks": checks,
        "blocking_reasons": list(dict.fromkeys(reasons)),
        "budget_preview": budget,
        "frame_reference_preview": frame_sources,
        "owner_scoped": True,
        "read_only": True,
        "can_queue": False,
        "can_generate": False,
        "gpu_authorized": False,
    }


class FrameTransferIssueBody(ProductionReadinessBody):
    """Exact frozen source-manifest SHA; not a production or GPU request."""

    expected_source_bindings_sha256: str = Field(pattern=_HASH_PATTERN)


@router.post("/studio/storypacks/owner-review/frame-transfer/issue")
async def issue_owner_frame_transfer(
    request: Request, principal: OwnerIdentity,
) -> dict:
    """Owner-loopback only: issue one-use data transfer to a paired device."""
    body = await _read(request, FrameTransferIssueBody)
    _authorize(principal, body.subject_key)
    _authorize_asset_use(principal, body.subject_key)
    pack = _pack(body)
    source_sha = body.expected_source_bindings_sha256
    services = request.app.state.services

    def validate_and_bind() -> dict:
        # 每次重查 Owner 当前凭据、审计撤销与真实文件哈希，避免复用旧预检。
        _service(request).verify(
            pack=pack, subject_key=body.subject_key,
            review_id=body.storyboard_review_id, principal=principal,
        )
        _asset_use(request).verify(
            pack=pack, claims=body.claims, subject_key=body.subject_key,
            principal=principal, attestation_id=body.attestation_id,
        )
        candidate = complete_storypack_episode_preview(
            pack, body.storypack_sha256, body.completion,
        )
        episode = Episode.model_validate(candidate["episode"])
        budget = services.production.preview_budget(episode)
        if not budget["allowed"]:
            raise FrameTransferError("FRAME_TRANSFER_EPISODE_BUDGET_BLOCKED")
        review = _service(request).subject(pack)["review"]
        preview = inspect_frame_sources(pack, episode, review)
        if (
            not preview["mac_managed_content_verified"]
            or preview["source_bindings_sha256"] != source_sha
        ):
            raise FrameTransferError("FRAME_TRANSFER_SOURCE_OR_SHA_STALE")
        return preview

    try:
        # 同步导出 128 MiB 上限的素材 ZIP 放到线程池，不阻塞主事件循环。
        preview = await run_in_threadpool(validate_and_bind)
        registry = request.app.state.frame_transfer_tickets
        return await run_in_threadpool(
            registry.issue,
            manifest_sha256=source_sha,
            export=lambda path: export_frame_bundle(
                services.settings.paths.objects_dir, preview, path
            ),
            validate_current=lambda: validate_and_bind(),
        )
    except (StoryboardReviewError, AssetUseError, FrameTransferError) as error:
        code = error.code if hasattr(error, "code") else str(error)
        raise ApiError(
            status_code=409, code=code,
            message="素材传输所需的 Owner 审核或来源版本已失效。",
            retryable=False,
        ) from error
    except (EpisodeCandidateError, ValidationError) as error:
        raise ApiError(
            status_code=422, code="FRAME_TRANSFER_EPISODE_INVALID",
            message="素材传输对应的 Episode 合同无效。",
            retryable=False,
        ) from error
