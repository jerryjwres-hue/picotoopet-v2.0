"""Production Plan v1.1: immutable scoped reference identity without altering v1.0.

Legacy v1.0 JSON remains byte-for-byte; only explicitly created v1.1 plans
include reference_asset fields on each task. Do not backfill frozen old plans.
"""
from __future__ import annotations

from datetime import datetime
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


class WorkerReferenceSnapshotWitnessV11(BaseModel):
    """Untrusted Windows assertion; independently checking its bytes is impossible on Mac."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    production_task_id: str = Field(min_length=1, max_length=160)
    shot_id: str = Field(min_length=1, max_length=80)
    asset_id: str = Field(min_length=1, max_length=160)
    approval_id: str = Field(min_length=1, max_length=160)
    approval_request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_bytes: int = Field(gt=0, le=32 * 1024 * 1024)
    source_relative_path: str = Field(min_length=1, max_length=300)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_bytes: int = Field(gt=0, le=32 * 1024 * 1024)
    snapshot_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_relative_path: str = Field(min_length=1, max_length=300)


class WorkerWitnessV11(BaseModel):
    """Canonical signature-covered proposed claim, NOT a production credential.

    Signature is intentionally only data until an independently provisioned,
    revocable Worker public key is pinned to the paired device by Core. Current
    API bearer is NOT an acceptable source for such a key. No nonce ledger or
    Windows/Comfy attestation issuer exists yet: shipping Claim stays disabled.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["production.worker_witness.v1"] = "production.worker_witness.v1"
    algorithm: Literal["ed25519"] = "ed25519"
    worker_key_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    executor_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    production_job_id: str = Field(min_length=1, max_length=160)
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    issued_at: datetime
    expires_at: datetime
    nonce: str = Field(pattern=r"^[0-9a-f]{64}$")
    worker_executable_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    journal_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    journal_generation: int = Field(ge=0)
    journal_state: Literal["NO_PRIOR_POST", "BOUND_RECOVERY", "UNCERTAIN"]
    references: tuple[WorkerReferenceSnapshotWitnessV11, ...] = Field(min_length=1, max_length=12)
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    @model_validator(mode="after")
    def _strict_witness_shape(self) -> WorkerWitnessV11:
        from datetime import timedelta

        if (
            self.issued_at.tzinfo is None
            or self.expires_at.tzinfo is None
            or self.issued_at.utcoffset() != timedelta(0)
            or self.expires_at.utcoffset() != timedelta(0)
            or not timedelta(0) < self.expires_at - self.issued_at <= timedelta(seconds=30)
        ):
            raise ValueError("PRODUCTION_V11_WITNESS_WINDOW_INVALID")
        if (
            self.nonce == "0" * 64
            or self.signature == "0" * 128
            or self.worker_executable_sha256 == "0" * 64
        ):
            raise ValueError("PRODUCTION_V11_WITNESS_PLACEHOLDER_REJECTED")
        ids = [item.production_task_id for item in self.references]
        if len(ids) != len(set(ids)) or len({item.shot_id for item in self.references}) != len(ids):
            raise ValueError("PRODUCTION_V11_WITNESS_DUPLICATE_REFERENCE")
        return self

    def signed_payload(self) -> bytes:
        """Domain-separated canonical JSON; NEVER include or trust payload-supplied keys."""
        import json

        fields = self.model_dump(mode="json", exclude={"signature"})
        return (
            b"picotoopet.production.worker_witness.v1\n"
            + json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )

    def require_fresh(self, now: datetime) -> None:
        from datetime import timedelta

        if now.tzinfo is None:
            raise ValueError("PRODUCTION_V11_WITNESS_CLOCK_INVALID")
        if self.issued_at > now + timedelta(seconds=5) or self.expires_at <= now:
            raise ValueError("PRODUCTION_V11_WITNESS_STALE")
