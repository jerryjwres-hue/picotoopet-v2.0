"""Renderer-specific frozen LTX pilot plan compiler.

Reuse Core's existing Creative Package, reference approval and compiler.
This module can durably freeze a held job, but cannot admit a worker.
The legacy v1.0/1.1 parser deliberately rejects this plan until its own
execution path is wired end to end.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from picotoopet_core.approvals.service import ApprovalService
from picotoopet_core.creative.models import CreativeJobStatus, CreativeQualityOutcome
from picotoopet_core.creative.store import CreativeArtifactStore
from .compiler import compile_production_plan
from .reference_assets import (
    LtxReferenceAssetIdentityV1,
    verify_persisted_ltx_reference_approval,
)
from .reference_registration import ReferenceRegistrationService
from .service import ProductionService
from .models import ProductionJobRecord, ProductionJobStatus, ProductionProfile

LTX_SCOPE = "ltx.desktop.local.i2v.production.v1"


class LtxPilotPlanV12(BaseModel):
    """One immutable 4s I2V shot; vendor geometry is audited after rendering."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.2"] = "1.2"
    production_profile: Literal["production.ltx.desktop.local.v1"] = "production.ltx.desktop.local.v1"
    workflow_id: Literal["ltx.desktop.local.i2v.v1"] = "ltx.desktop.local.i2v.v1"
    production_job_id: str
    creative_package_id: str
    creative_package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_key: str
    source_output_profile: Literal["video.vertical.v1"]
    shot_id: str
    production_task_id: str
    prompt: str = Field(min_length=1, max_length=5000)
    seed: int = Field(ge=0, le=2147483647, strict=True)
    model: Literal["ltx-2.5-fast"] = "ltx-2.5-fast"
    resolution: Literal["720p"] = "720p"
    aspect_ratio: Literal["9:16"] = "9:16"
    duration_seconds: Literal[4] = 4
    fps: Literal[24] = 24
    reference_asset: LtxReferenceAssetIdentityV1

    @model_validator(mode="after")
    def _exact_reference_binding(self) -> LtxPilotPlanV12:
        # 01. Bind the per-shot consent to this exact source and plan identity.
        ref = self.reference_asset
        if (
            ref.production_job_id != self.production_job_id
            or ref.production_task_id != self.production_task_id
            or ref.creative_package_id != self.creative_package_id
            or ref.creative_package_digest != self.creative_package_digest
            or ref.shot_id != self.shot_id
            or ref.rights_scope != LTX_SCOPE
        ):
            raise ValueError("LTX_PLAN_REFERENCE_BINDING_MISMATCH")
        return self

    def digest(self) -> str:
        # 02. Use the existing Core canonical digest, not another signature scheme.
        return ProductionService._digest(self.model_dump(mode="json"))


def compile_ltx_pilot_plan(
    service: ProductionService, *, production_job_id: str,
    creative_package_id: str, approved_reference_id: str,
    selected_shot_id: str | None = None,
) -> LtxPilotPlanV12:
    """Compile one exact approved shot; legacy requests remain first-shot only."""
    # 03. Verify frozen source bytes and current goal/Creative lineage.
    job_id = str(UUID(production_job_id))
    package = service._creative_package_by_id(creative_package_id)
    db = service.repository.database
    creative = service.creative_repository.get_job(package.creative_job_id)
    if (package.quality_outcome is not CreativeQualityOutcome.PASS
        or creative.status is not CreativeJobStatus.CREATIVE_READY):
        raise ValueError("LTX_PLAN_CREATIVE_NOT_ELIGIBLE")
    source = db.fetchone(
        "SELECT goal_id FROM creative_goal_source_sets WHERE creative_job_id=?",
        (package.creative_job_id,),
    )
    if source is None or creative.project_key != f"goal-{source['goal_id']}":
        raise ValueError("LTX_PLAN_GOAL_LINEAGE_INVALID")
    frozen = db.fetchone(
        "SELECT * FROM creative_packages WHERE creative_package_id=?",
        (creative_package_id,),
    )
    # The original registration verifier compares ZIP bytes AND SQL manifest.
    # No second artifact registry or new database table is needed.
    verifier = ReferenceRegistrationService(
        db, None, CreativeArtifactStore(service.store.paths),
    )
    manifest = verifier._verify_package_artifact(frozen)
    service._verify_dynamic_reference_scope(package)

    # 04. Read the existing exact Owner decision, never a supplied consent flag.
    row = db.fetchone("SELECT * FROM approvals WHERE approval_id=?", (approved_reference_id,))
    if row is None or row["approval_type"] != "production.reference_asset.v1":
        raise ValueError("LTX_PLAN_REFERENCE_NOT_APPROVED")
    scope = json.loads(row["scope_json"])
    if (
        scope.get("schema_version") != "reference_consent_batch.v1"
        or scope.get("rights_scope") != LTX_SCOPE
        or scope.get("goal_id") != source["goal_id"]
        or scope.get("creative_job_id") != package.creative_job_id
        or scope.get("creative_package_id") != package.creative_package_id
        or scope.get("creative_package_digest") != package.package_digest
    ):
        raise ValueError("LTX_PLAN_REFERENCE_SCOPE_MISMATCH")
    refs = scope.get("references")
    # 05. Preserve the historical single-first-shot contract. An explicit
    #     selection may use a complete three-shot consent, but never a partial
    #     or duplicate image batch. Each resulting plan is still one task.
    shot_plan = manifest["stage_results"]["shot_plan.v1"]["shots"]
    if not shot_plan or not isinstance(refs, list) or any(not isinstance(r, dict) for r in refs):
        raise ValueError("LTX_PLAN_FIRST_SHOT_ONLY")
    if selected_shot_id is None:
        if len(refs) != 1 or refs[0].get("shot_id") != shot_plan[0].get("shot_id"):
            raise ValueError("LTX_PLAN_FIRST_SHOT_ONLY")
        entry = refs[0]
        approved_shots = {entry["shot_id"]}
    else:
        source_shots = {shot["shot_id"] for shot in shot_plan}
        approved_shots = {item.get("shot_id") for item in refs}
        if (len(shot_plan) != 3 or len(refs) != 3 or len(source_shots) != 3
            or approved_shots != source_shots or selected_shot_id not in source_shots
            or len({item.get("sha256") for item in refs}) != 3
            or len({item.get("input_relative_path") for item in refs}) != 3
            or any(shot.get("duration_seconds") != 4 for shot in shot_plan)):
            raise ValueError("LTX_PLAN_FULL_SHOT_CONSENT_REQUIRED")
        entry = next(item for item in refs if item["shot_id"] == selected_shot_id)
    sanitized = dict(manifest)
    sanitized["trusted_local_assets"] = {
        item["shot_id"]: item["input_relative_path"] for item in refs
    }
    if any(shot["render_intent"] != "IMAGE_TO_VIDEO" for shot in shot_plan
           if shot["shot_id"] in approved_shots):
        sanitized = service._bridge_sealed_v2_manifest(
            sanitized, creative, approved_shots, pilot_first_shot=selected_shot_id is None,
        )
    base = compile_production_plan(job_id, sanitized, package.package_digest)
    first = next(task for task in base.tasks if task.shot_id == entry["shot_id"])
    if (
        base.output_profile_id.value != "video.vertical.v1"
        or first.render_intent != "IMAGE_TO_VIDEO"
        or first.execution_disposition.value != "Executable"
        or first.target_duration_ms != 4000
        or first.fps != 24
    ):
        raise ValueError("LTX_PLAN_PORTRAIT_4S_REQUIRED")

    # 06. Verify exact approved first-frame identity at compile time.
    #     The Core has not hashed Windows bytes; the worker must rehash them.
    reference = LtxReferenceAssetIdentityV1(
        schema_version="reference_asset.v1",
        asset_id=entry["asset_id"], goal_id=source["goal_id"],
        creative_job_id=package.creative_job_id,
        creative_package_id=package.creative_package_id,
        production_job_id=job_id, production_task_id=first.production_task_id,
        shot_id=first.shot_id, creative_package_digest=package.package_digest,
        input_relative_path=entry["input_relative_path"],
        sha256=entry["sha256"], bytes=entry["bytes"],
        source_reference=entry["source_reference"], source_digest=entry["source_digest"],
        rights_scope=LTX_SCOPE, approval_id=approved_reference_id,
        approval_request_digest=ApprovalService._request_digest(row),
    )
    verify_persisted_ltx_reference_approval(db, reference)

    # 07. LTX seed range is the existing Windows int32 transport contract.
    #     Do not claim a fixed output width/height or 97 frames from 720p alone.
    return LtxPilotPlanV12(
        production_job_id=job_id,
        creative_package_id=package.creative_package_id,
        creative_package_digest=package.package_digest,
        project_key=base.project_key,
        source_output_profile="video.vertical.v1",
        shot_id=first.shot_id, production_task_id=first.production_task_id,
        prompt=first.positive_prompt, seed=first.seed & 0x7fffffff,
        reference_asset=reference,
    )


def recompile_frozen_ltx_plan(service: ProductionService, plan: LtxPilotPlanV12) -> LtxPilotPlanV12:
    """Recheck the original selection against the current exact approved scope."""
    # 01. Full consent requires explicit shot selection at every live check.
    row = service.repository.database.fetchone(
        "SELECT scope_json FROM approvals WHERE approval_id=?",
        (plan.reference_asset.approval_id,),
    )
    if row is None:
        raise ValueError("LTX_PLAN_REFERENCE_NOT_APPROVED")
    scope = json.loads(row["scope_json"])
    refs = scope.get("references") if isinstance(scope, dict) else None
    if not isinstance(refs, list) or len(refs) not in (1, 3):
        raise ValueError("LTX_PLAN_REFERENCE_SCOPE_MISMATCH")
    return compile_ltx_pilot_plan(
        service, production_job_id=plan.production_job_id,
        creative_package_id=plan.creative_package_id,
        approved_reference_id=plan.reference_asset.approval_id,
        selected_shot_id=plan.shot_id if len(refs) == 3 else None,
    )


class LtxPilotFreezeRequestV12(BaseModel):
    """Explicit new-job request, not an upgrade or a GPU authorization."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    creative_package_id: str
    approved_reference_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=200)
    # 01. Explicit shot selection is opt-in; old callers freeze shot one.
    selected_shot_id: str | None = Field(default=None, min_length=1, max_length=80)
    # 02. Stable per-click reroll identity; the frozen plan schema is unchanged.
    reroll_of_job_id: UUID | None = None
    reroll_variant: UUID | None = None

    @model_validator(mode="after")
    def _reroll_pair(self) -> LtxPilotFreezeRequestV12:
        if ((self.reroll_of_job_id is None) != (self.reroll_variant is None)
            or self.reroll_of_job_id == UUID(int=0) or self.reroll_variant == UUID(int=0)):
            raise ValueError("LTX_REROLL_IDENTITY_INVALID")
        return self


def freeze_ltx_pilot_job(
    service: ProductionService, request: LtxPilotFreezeRequestV12,
) -> ProductionJobRecord:
    """Atomically persist the immutable plan in the existing production table.

    No task is materialized while the LTX-specific signed worker path is absent.
    This is an explicit held reservation, not an executable job or approval.
    """
    db = service.repository.database
    package_id = str(UUID(request.creative_package_id))
    # 01. Compile, recheck current approval, and persist under the SAME
    #     database transaction. A concurrent revoke cannot race the freeze.
    with db.transaction() as connection:
        existing = connection.execute(
            "SELECT * FROM production_jobs WHERE idempotency_key=?",
            (request.idempotency_key,),
        ).fetchone()
        if existing is not None and (
            existing["production_profile"] != ProductionProfile.LTX_DESKTOP_LOCAL_V1.value
            or existing["creative_package_id"] != package_id
        ):
            raise ValueError("LTX_PLAN_IDEMPOTENCY_CONFLICT")
        # 04. Only a settled exact source may be rerolled; never reopen an
        #     uncertain vendor attempt or alter its original media evidence.
        source_plan = None
        if request.reroll_of_job_id is not None:
            source_id = str(request.reroll_of_job_id)
            if request.idempotency_key != f"reviewed-ltx-reroll-v12-{source_id}-{request.reroll_variant}":
                raise ValueError("LTX_REROLL_KEY_MISMATCH")
            source = connection.execute(
                "SELECT * FROM production_jobs WHERE production_job_id=?", (source_id,),
            ).fetchone()
            if (source is None or source["status"] != "NeedsHuman"
                or source["failure_code"] != "LTX_PILOT_REVIEW_REQUIRED"
                or source["lease_executor_id"] is not None or source["lease_token_digest"] is not None
                or source["lease_expires_at"] is not None):
                raise ValueError("LTX_REROLL_SOURCE_NOT_SETTLED")
            source_plan = load_frozen_ltx_pilot_plan(service, source_id)
            if (source_plan.creative_package_id != package_id
                or source_plan.reference_asset.approval_id != request.approved_reference_id
                or request.selected_shot_id not in (None, source_plan.shot_id)
                or recompile_frozen_ltx_plan(service, source_plan) != source_plan):
                raise ValueError("LTX_REROLL_SOURCE_MISMATCH")
            tasks = connection.execute(
                "SELECT * FROM production_tasks WHERE production_job_id=?", (source_id,),
            ).fetchall()
            attempts = connection.execute(
                "SELECT * FROM production_attempts WHERE production_job_id=?", (source_id,),
            ).fetchall()
            if (len(tasks) != 1 or len(attempts) != 1
                or tasks[0]["production_task_id"] != source_plan.production_task_id
                or tasks[0]["status"] != "Succeeded" or tasks[0]["attempt_count"] != 1
                or attempts[0]["production_task_id"] != source_plan.production_task_id
                or attempts[0]["status"] != "Succeeded" or not attempts[0]["ltx_result_digest"]):
                raise ValueError("LTX_REROLL_SOURCE_NOT_SETTLED")
        elif request.idempotency_key.startswith("reviewed-ltx-reroll-v12-"):
            raise ValueError("LTX_REROLL_KEY_MISMATCH")

        job_id = existing["production_job_id"] if existing is not None else str(uuid4())
        plan = compile_ltx_pilot_plan(
            service, production_job_id=job_id, creative_package_id=package_id,
            approved_reference_id=request.approved_reference_id,
            selected_shot_id=request.selected_shot_id,
        )
        if source_plan is not None:
            # 05. New job-derived seed, same approved image and prompt.
            #     Retry of the same variant returns the same frozen identity.
            if (plan.shot_id != source_plan.shot_id or plan.prompt != source_plan.prompt
                or plan.reference_asset.model_dump(exclude={"production_job_id", "production_task_id"})
                != source_plan.reference_asset.model_dump(exclude={"production_job_id", "production_task_id"})
                or plan.seed == source_plan.seed):
                raise ValueError("LTX_REROLL_SOURCE_MISMATCH")
        digest = plan.digest()
        encoded = json.dumps(
            plan.model_dump(mode="json"), sort_keys=True,
            separators=(",", ":"), ensure_ascii=False,
        )
        # 02. Exact retries return the already persisted job, never replace
        #     its source, shot, renderer, approval, or frozen plan bytes.
        if existing is not None:
            if (
                existing["plan_digest"] != digest or existing["plan_json"] != encoded
                or existing["creative_package_digest"] != plan.creative_package_digest
                or existing["project_key"] != plan.project_key
                or existing["status"] != ProductionJobStatus.NEEDS_HUMAN.value
            ):
                raise ValueError("LTX_PLAN_IDEMPOTENCY_CONFLICT")
            return service.repository.get_job(job_id)

        # 03. Reuse production_jobs rather than create a second scheduler.
        #     No Ready row, task, lease, attempt, nonce, or vendor POST.
        stamp = datetime.now(UTC).isoformat()
        connection.execute(
            "INSERT INTO production_jobs("
            "production_job_id,creative_package_id,creative_package_digest,"
            "project_key,production_profile,plan_digest,plan_json,status,"
            "failure_code,idempotency_key,created_at,updated_at,finished_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, package_id, plan.creative_package_digest, plan.project_key,
             plan.production_profile, digest, encoded,
             ProductionJobStatus.NEEDS_HUMAN.value,
             "LTX_SIGNED_WORKER_NOT_ENABLED", request.idempotency_key,
             stamp, stamp, stamp),
        )
        return service.repository.get_job(job_id)


def load_frozen_ltx_pilot_plan(
    service: ProductionService, production_job_id: str,
) -> LtxPilotPlanV12:
    """Read the separate frozen contract; legacy executable parser stays closed."""
    row = service.repository.database.fetchone(
        "SELECT * FROM production_jobs WHERE production_job_id=?",
        (production_job_id,),
    )
    if row is None:
        raise KeyError(production_job_id)
    if row["production_profile"] != ProductionProfile.LTX_DESKTOP_LOCAL_V1.value:
        raise ValueError("LTX_PLAN_PROFILE_MISMATCH")
    plan = LtxPilotPlanV12.model_validate_json(row["plan_json"])
    # 04. Fail closed on stored plan or source identity tampering.
    if (
        row["plan_digest"] != plan.digest()
        or row["production_job_id"] != plan.production_job_id
        or row["creative_package_id"] != plan.creative_package_id
        or row["creative_package_digest"] != plan.creative_package_digest
        or row["project_key"] != plan.project_key
    ):
        raise ValueError("LTX_PLAN_PERSISTED_IDENTITY_MISMATCH")
    return plan
