"""Renderer-specific frozen LTX pilot plan compiler.

Reuse Core's existing Creative Package, reference approval and compiler.
This module does NOT register a job or admit a worker. The legacy v1.0/1.1
parser deliberately cannot accept this new plan until its execution path is
wired end to end.
"""
from __future__ import annotations

import json
from typing import Literal
from uuid import UUID

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
) -> LtxPilotPlanV12:
    """Compile the FIRST approved shot from actual persisted Core records."""
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
    if not isinstance(refs, list) or len(refs) != 1 or not isinstance(refs[0], dict):
        raise ValueError("LTX_PLAN_FIRST_SHOT_ONLY")
    entry = refs[0]

    # 05. Reuse Core's sealed-v2 bridge when necessary; preserve source profile.
    #     Existing v1 packages must already designate the first shot as I2V.
    shot_plan = manifest["stage_results"]["shot_plan.v1"]["shots"]
    if not shot_plan or entry.get("shot_id") != shot_plan[0].get("shot_id"):
        raise ValueError("LTX_PLAN_FIRST_SHOT_ONLY")
    sanitized = dict(manifest)
    sanitized["trusted_local_assets"] = {
        entry["shot_id"]: entry["input_relative_path"],
    }
    if shot_plan[0]["render_intent"] != "IMAGE_TO_VIDEO":
        sanitized = service._bridge_sealed_v2_manifest(
            sanitized, creative, {entry["shot_id"]}, pilot_first_shot=True,
        )
    base = compile_production_plan(job_id, sanitized, package.package_digest)
    first = base.tasks[0]
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
