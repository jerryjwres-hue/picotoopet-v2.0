"""Production Plan v1.1: immutable scoped reference identity without altering v1.0.

Legacy v1.0 JSON remains byte-for-byte; only explicitly created v1.1 plans
include reference_asset fields on each task. Do not backfill frozen old plans.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import (
    ProductionExecutionDisposition,
    ProductionJobCreateRequest,
    ProductionTaskRecord,
    ProductionPlan,
    ProductionTaskPlan,
)
from .profile import I2V_WORKFLOW_ID, T2V_WORKFLOW_ID
from .reference_assets import ReferenceAssetIdentityV1, TrustedReferenceDescriptorV1


class ProductionTaskPlanV11(ProductionTaskPlan):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Required field (nullable for T2V): ensures old v1.0 task JSON cannot
    # silently parse as a new version via Pydantic union selection.
    reference_asset: ReferenceAssetIdentityV1 | None = Field(...)

    @model_validator(mode="after")
    def _reference_matches_task(self) -> ProductionTaskPlanV11:
        ref = self.reference_asset
        if self.render_intent == "IMAGE_TO_VIDEO":
            if (
                ref is None
                or self.workflow_id != I2V_WORKFLOW_ID
                or self.execution_disposition is not ProductionExecutionDisposition.EXECUTABLE
                or ref.production_task_id != self.production_task_id
                or ref.shot_id != self.shot_id
                or ref.input_relative_path != self.trusted_input_asset_ref
            ):
                raise ValueError("PRODUCTION_V11_I2V_REFERENCE_NOT_BOUND")
            pieces = ref.input_relative_path.split("/")
            base, sep, suffix = pieces[-1].rpartition(".")
            if (len(pieces) != 4
                or pieces[:2] != ["PicotooPet", "references"]
                or pieces[2] != ref.sha256
                or base != self.shot_id or not sep
                or suffix not in ("png", "jpg", "webp")):
                raise ValueError("PRODUCTION_V11_REFERENCE_NOT_CONTENT_ADDRESSED")
        elif (
            ref is not None
            or self.trusted_input_asset_ref is not None
            or (self.render_intent == "GENERATIVE_VIDEO" and self.workflow_id != T2V_WORKFLOW_ID)
        ):
            raise ValueError("PRODUCTION_V11_UNEXPECTED_REFERENCE")
        return self


class ProductionPlanV11(ProductionPlan):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.1"]
    tasks: list[ProductionTaskPlanV11] = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def _approved_reference_scope_is_bound(self) -> ProductionPlanV11:
        seen: set[str] = set()
        for task in self.tasks:
            ref = task.reference_asset
            if ref is None:
                continue
            if (
                ref.production_job_id != self.production_job_id
                or ref.creative_package_id != self.creative_package_id
                or ref.creative_package_digest != self.creative_package_digest
                or ref.asset_id in seen
            ):
                raise ValueError("PRODUCTION_V11_REFERENCE_JOB_OR_SOURCE_MISMATCH")
            seen.add(ref.asset_id)
        if not seen:
            raise ValueError("PRODUCTION_V11_REQUIRES_APPROVED_REFERENCE")
        return self


type VersionedProductionPlan = ProductionPlan | ProductionPlanV11


def parse_versioned_plan(raw: dict[str, object]) -> VersionedProductionPlan:
    version = raw.get("schema_version")
    if version == "1.0":
        return ProductionPlan.model_validate(raw)
    if version == "1.1":
        return ProductionPlanV11.model_validate(raw)
    raise ValueError("PRODUCTION_PLAN_SCHEMA_UNSUPPORTED")


def parse_versioned_task(raw: dict[str, object]) -> ProductionTaskPlan | ProductionTaskPlanV11:
    if "reference_asset" in raw:
        return ProductionTaskPlanV11.model_validate(raw)
    return ProductionTaskPlan.model_validate(raw)


class ProductionTaskRecordV11(ProductionTaskRecord):
    model_config = ConfigDict(extra="forbid")
    task_plan: ProductionTaskPlanV11


class ProductionJobCreateV11Request(ProductionJobCreateRequest):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.1"] = "1.1"
    approved_reference_ids: list[str] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def _unique_approval_ids(self) -> ProductionJobCreateV11Request:
        if len(set(self.approved_reference_ids)) != len(self.approved_reference_ids):
            raise ValueError("PRODUCTION_V11_APPROVAL_DUPLICATED")
        return self


class ApprovedReferenceAuthorizationV11(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["reference_authorization.v1"] = "reference_authorization.v1"
    production_job_id: str
    production_task_id: str
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    descriptor: TrustedReferenceDescriptorV1
    reference_asset: ReferenceAssetIdentityV1
