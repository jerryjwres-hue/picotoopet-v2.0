"""Device-authenticated, one-use, TLS-required private frame ZIP retrieval.

Issuing a ticket is exclusively a scoped Owner loopback operation. Device
Bearer alone never grants permission to enumerate or fetch managed sources.
"""

from __future__ import annotations

import json
from ipaddress import ip_address
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fastapi import APIRouter, Depends, Header, Request, Response
from starlette.background import BackgroundTask
from starlette.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from picotoopet_core.api.errors import ApiError
from picotoopet_core.audit.writer import AuditWriter, canonical_hash
from picotoopet_core.domain.episode import Episode
from picotoopet_core.domain.storypack_assets import inspect_recorded_asset_refs
from picotoopet_core.domain.storypack_frame_sources import validate_episode_frame_manifest
from picotoopet_core.domain.storypack_master_evidence import MasterEvidenceError, MasterEvidenceService
from picotoopet_core.domain.frame_transfer_tickets import FrameTransferError
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])
_UNTRUSTED_PROXY_HEADERS = (
    "forwarded", "x-forwarded-for", "x-forwarded-proto", "x-real-ip",
)


def _require_secure_delivery_peer(request: Request) -> None:
    """Allow HTTPS remote delivery or direct local testing, never LAN HTTP."""
    address = request.client.host if request.client is not None else ""
    try:
        local = ip_address(address).is_loopback
    except ValueError:
        local = False

    # 不接受代理自行声明的 HTTPS；只相信 ASGI socket 真实看到的 scheme。
    if any(name in request.headers for name in _UNTRUSTED_PROXY_HEADERS):
        raise ApiError(
            status_code=403, code="FRAME_TRANSFER_UNTRUSTED_PROXY",
            message="素材下载需要可信加密连接。", retryable=False,
        )
    if request.scope.get("scheme") != "https" and not local:
        raise ApiError(
            status_code=403, code="FRAME_TRANSFER_TLS_REQUIRED",
            message="远程素材下载必须使用加密连接。", retryable=False,
        )


@router.post("/studio/frame-transfer/claim")
async def claim_pending_owner_frame_transfer(request: Request, response: Response) -> dict | None:
    """Paired device atomically claims the one already-approved data transfer."""
    _require_secure_delivery_peer(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        result = await run_in_threadpool(
            request.app.state.frame_transfer_tickets.claim_pending
        )
    except FrameTransferError as error:
        raise ApiError(
            status_code=409, code=str(error),
            message="已审核的素材传输申请失效，请重新由主人审核。",
            retryable=False,
        ) from error
    if result is None:
        response.status_code = 204
        return None
    return result


@router.get("/studio/frame-transfer/download")
async def download_staged_frame_bundle(
    request: Request,
    transfer_ticket: str = Header(
        alias="X-Picotoo-Transfer-Ticket", min_length=20, max_length=160
    ),
) -> FileResponse:
    """Stream a single-use ZIP; recheck Owner revocation before first byte."""
    _require_secure_delivery_peer(request)
    registry = request.app.state.frame_transfer_tickets
    try:
        item = await run_in_threadpool(registry.consume, transfer_ticket)
    except FrameTransferError as error:
        raise ApiError(
            status_code=409, code=str(error),
            message="素材传输凭据失效、已使用或来源已改变。",
            retryable=False,
        ) from error

    return FileResponse(
        path=item.path,
        media_type="application/zip",
        filename="PicotooPet-Frame-Sources.zip",
        content_disposition_type="attachment",
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "X-Picotoo-Source-Bindings-Sha256": item.manifest_sha256,
            "X-Picotoo-Bundle-Sha256": item.bundle_sha256,
        },
        background=BackgroundTask(registry.finish, item.path),
    )


class _StagedBinding(BaseModel):
    """Windows reports identity and SHA only; never discloses its private file paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    shot_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    role: Literal["first", "last"]
    asset_ref: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,99}$")
    managed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _StudioStagingReport(BaseModel):
    """Data-only, paired-device statement; not an independent Worker proof."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    episode_id: str = Field(min_length=1, max_length=100)
    source_bindings_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    storypack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    owner_subject_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bindings: list[_StagedBinding] = Field(min_length=1, max_length=960)
    verified_bytes: int = Field(ge=1, le=128 * 1024 * 1024)
    worker_local_bytes_verified: Literal[True]


def _record_stage(request: Request, report: _StudioStagingReport) -> dict:
    """Bind a device-reported copy to a real immutable frozen Episode if one exists."""
    services = request.app.state.services
    with services.database.transaction() as db:
        freeze = db.execute(
            "SELECT audit_id FROM audit_events "
            "WHERE action='episode.freeze_owner_hold' AND resource_id=?",
            (report.episode_id,),
        ).fetchall()
        if not freeze:
            # An Owner may issue the data transfer before freezing any Production Job.
            return {
                "status": "STAGED_DATA_NOT_YET_FROZEN",
                "episode_id": report.episode_id,
                "core_staging_linked": False,
                "worker_independently_verified": False,
                "can_lease": False, "gpu_authorized": False,
            }
        if len(freeze) != 1 or not services.owner_mode_gpu_hold:
            raise MasterEvidenceError("STAGING_FROZEN_JOB_AMBIGUOUS_OR_UNPROTECTED")

        # Core reconstructs the plan; paired-device input is never a Plan authority.
        plan = MasterEvidenceService._frozen(db, report.episode_id)
        plan_sha = canonical_hash(plan)
        if (plan.get("source_bindings_sha256") != report.source_bindings_sha256
                or plan.get("storypack_sha256") != report.storypack_sha256):
            raise MasterEvidenceError("STAGING_FROZEN_PLAN_SOURCE_MISMATCH")
        episode_row = db.execute(
            "SELECT spec_json FROM production_episodes WHERE episode_id=?",
            (report.episode_id,),
        ).fetchone()
        if episode_row is None:
            raise MasterEvidenceError("STAGING_EPISODE_NOT_FOUND")
        episode = Episode.model_validate_json(episode_row["spec_json"])
        if canonical_hash(episode.model_dump(mode="json")) != plan["episode_sha256"]:
            raise MasterEvidenceError("STAGING_EPISODE_CHANGED")

        keyframes = db.execute(
            "SELECT payload_json FROM tasks "
            "WHERE task_type='gen.keyframe' "
            "AND json_extract(payload_json, '$.episode_id')=? ORDER BY rowid",
            (report.episode_id,),
        ).fetchall()
        if len(keyframes) != len(episode.shots):
            raise MasterEvidenceError("STAGING_KEYFRAME_TASK_SET_CHANGED")
        frozen_manifest = None
        for index, row in enumerate(keyframes):
            data = json.loads(row["payload_json"])
            jobs = data["jobs"]
            if (data["shot_id"] != episode.shots[index].shot_id
                    or jobs.get("source_bindings_sha256") != report.source_bindings_sha256):
                raise MasterEvidenceError("STAGING_TASK_BINDINGS_CHANGED")
            if frozen_manifest is None:
                frozen_manifest = jobs.get("frame_source_manifest")
            elif frozen_manifest != jobs.get("frame_source_manifest"):
                raise MasterEvidenceError("STAGING_TASK_MANIFEST_DRIFT")
        try:
            canonical_manifest = validate_episode_frame_manifest(
                episode, frozen_manifest, report.source_bindings_sha256
            )
        except ValueError as error:
            raise MasterEvidenceError("STAGING_MANIFEST_INVALID") from error
        if canonical_manifest.get("owner_subject_sha256") != report.owner_subject_sha256:
            raise MasterEvidenceError("STAGING_OWNER_SUBJECT_MISMATCH")

        expected = sorted(
            (item["shot_id"], item["role"], item["asset_ref"], item["managed_sha256"])
            for item in canonical_manifest["bindings"]
        )
        received = sorted(
            (item.shot_id, item.role, item.asset_ref, item.managed_sha256)
            for item in report.bindings
        )
        if received != expected or len(set(received)) != len(received):
            raise MasterEvidenceError("STAGING_SHOT_BINDINGS_MISMATCH")

        # Rehash Mac originals too. We CANNOT independently read a Windows disk.
        checked_hashes = {}
        for shot, role, asset_ref, sha in expected:
            if asset_ref in checked_hashes and checked_hashes[asset_ref] != sha:
                raise MasterEvidenceError("STAGING_SOURCE_REF_CONFLICT")
            checked_hashes[asset_ref] = sha
        checks = inspect_recorded_asset_refs(
            services.database, sorted(checked_hashes),
            managed_objects_dir=services.settings.paths.objects_dir,
        )
        if any(
            row["recorded_sha256"] != checked_hashes[row["ref"]]
            or row["content_integrity_verified"] is not True
            for row in checks
        ):
            raise MasterEvidenceError("STAGING_MAC_SOURCE_BYTES_CHANGED")

        digest = canonical_hash({
            "contract": "picotoo.windows-studio-staged-refs.v1",
            "episode_id": report.episode_id,
            "frozen_plan_sha256": plan_sha,
            "source_bindings_sha256": report.source_bindings_sha256,
            "owner_subject_sha256": report.owner_subject_sha256,
            "bindings": [list(row) for row in expected],
            "verified_bytes_reported": report.verified_bytes,
        })
        old = db.execute(
            "SELECT audit_id, details_redacted_json FROM audit_events "
            "WHERE action='episode.windows_staging_report' AND resource_id=?",
            (report.episode_id,),
        ).fetchall()
        if len(old) > 1 or (
            old and json.loads(old[0]["details_redacted_json"]).get("report_sha256") != digest
        ):
            raise MasterEvidenceError("STAGING_REPORT_CONFLICT")
        if not old:
            AuditWriter(services.database).append(
                connection=db, trace_id=request.state.trace_id,
                actor_type="paired_device", actor_id="authenticated-device",
                action="episode.windows_staging_report",
                resource_type="episode", resource_id=report.episode_id,
                decision="DATA_REPORTED_GPU_HOLD",
                reason_code="WORKER_ATTESTATION_AND_GPU_ADMISSION_PENDING",
                details={
                    "frozen_plan_sha256": plan_sha,
                    "source_bindings_sha256": report.source_bindings_sha256,
                    "report_sha256": digest,
                    "verified_bytes_reported": report.verified_bytes,
                    "staged_binding_count": len(received),
                },
            )
        return {
            "status": "WINDOWS_STAGING_REPORTED_FOR_FROZEN_PLAN",
            "episode_id": report.episode_id,
            "frozen_plan_sha256": plan_sha,
            "report_sha256": digest,
            "already_reported": bool(old),
            "core_staging_linked": True,
            # A device bearer can assert staging; it cannot attest a Worker or authorize GPU.
            "worker_independently_verified": False,
            "can_lease": False, "can_generate": False, "gpu_authorized": False,
        }


@router.post("/studio/frame-transfer/staging-report")
async def report_windows_staged_frames(
    request: Request, body: _StudioStagingReport,
) -> dict:
    """Record data-only Windows Studio staging without changing queues or leases."""
    _require_secure_delivery_peer(request)
    try:
        return await run_in_threadpool(_record_stage, request, body)
    except (MasterEvidenceError, ValueError, TypeError, KeyError) as error:
        raise ApiError(
            status_code=409,
            code=error.code if isinstance(error, MasterEvidenceError) else
                 "STAGING_REPORT_INVALID_OR_STALE",
            message="素材报告与已冻结的 Episode 或当前来源不一致，保持 GPU HOLD。",
            retryable=False,
        ) from error
