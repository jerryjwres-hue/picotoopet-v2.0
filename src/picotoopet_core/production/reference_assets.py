"""Versioned reference-image identity and read-only Core approval verification.

NOT a second asset registry: approval authority stays in the existing approvals
table. A Windows-owned file digest remains a *claim* until Windows verifies bytes.
This module does not amend the frozen ProductionPlan v1.0 or mint user consent.
"""

from __future__ import annotations

import hmac
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import field_validator, model_validator

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.approvals.service import ApprovalService
from picotoopet_core.db.database import Database

_SCOPE = "wan22.i2v.production.v1"
_APPROVAL_TYPE = "production.reference_asset.v1"


class ReferenceAssetIdentityV1(BaseModel):
    """Proposed strictly typed projection of one already-reviewed image reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["reference_asset.v1"]
    asset_id: str = Field(min_length=36, max_length=36)
    goal_id: str = Field(min_length=1, max_length=160)
    creative_job_id: str = Field(min_length=1, max_length=160)
    creative_package_id: str = Field(min_length=1, max_length=160)
    production_job_id: str = Field(min_length=1, max_length=160)
    production_task_id: str = Field(min_length=1, max_length=160)
    shot_id: str = Field(min_length=1, max_length=80)
    creative_package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_relative_path: str = Field(min_length=1, max_length=300)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0, le=32 * 1024 * 1024)
    source_reference: str = Field(min_length=1, max_length=240)
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rights_scope: Literal["wan22.i2v.production.v1"]
    approval_id: str = Field(min_length=1, max_length=160)
    approval_request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("asset_id")
    @classmethod
    def _stable_uuid_asset_id(cls, value: str) -> str:
        """Identity must originate from a Core UUID allocation, not the path or digest."""
        if str(UUID(value)) != value:
            raise ValueError("REFERENCE_ASSET_ID_NONCANONICAL")
        return value

    @model_validator(mode="after")
    def _asset_id_must_be_separate_from_approval(self) -> ReferenceAssetIdentityV1:
        if self.asset_id == self.approval_id:
            raise ValueError("REFERENCE_ASSET_ID_MUST_DIFFER_FROM_APPROVAL_ID")
        return self


class TrustedReferenceDescriptorV1(BaseModel):
    """Exact six-field projection expected by Codex #107. Never authorization itself."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str
    shot_id: str
    asset_id: str
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_length: int = Field(gt=0)


def approved_reference_descriptor(
    database: Database, reference: ReferenceAssetIdentityV1
) -> TrustedReferenceDescriptorV1:
    """Build Codex's descriptor ONLY after exact authenticated Core approval lookup.

    Caller MUST also bind the same reference to the eventual immutable v1.1
    Production Plan before any GPU job can run; this is no plan/claim bypass.
    """
    verify_persisted_reference_approval(database, reference)
    return TrustedReferenceDescriptorV1(
        approval_id=reference.approval_id,
        shot_id=reference.shot_id,
        asset_id=reference.asset_id,
        relative_path=reference.input_relative_path,
        sha256=reference.sha256,
        byte_length=reference.bytes,
    )


def verify_persisted_reference_approval(
    database: Database, reference: ReferenceAssetIdentityV1
) -> None:
    """Read only; fail closed unless existing Core approval matches every identity.

    An approval here is not a claim that the Mac inspected the Windows image.
    The immutable Windows byte check and future plan projection are separate.
    """

    row = database.fetchone(
        "SELECT * FROM approvals WHERE approval_id=?", (reference.approval_id,)
    )
    if (
        row is None
        or row["approval_type"] != _APPROVAL_TYPE
        or row["task_id"] is not None
        or row["status"] != "Approved"
        or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC)
        or not row["resolved_by"]
        or not row["resolved_at"]
        or not hmac.compare_digest(
            ApprovalService._request_digest(row), reference.approval_request_digest
        )
    ):
        raise ValueError("REFERENCE_ASSET_APPROVAL_NOT_VERIFIED")

    try:
        scope = json.loads(row["scope_json"])
    except (ValueError, TypeError) as error:
        raise ValueError("REFERENCE_ASSET_APPROVAL_NOT_VERIFIED") from error

    # Approval occurs *after* Creative Package freeze, but *before* a new
    # Production Job/Task ID exists. Scope may bind only stable source identity.
    # Post-freeze production IDs MUST be independently checked against a
    # durable v1.1 Plan by the future authenticated Core authorization endpoint.
    # A bool approval result alone does NOT authorize a GPU submission.
    expected = {
        "asset_id": reference.asset_id,
        "goal_id": reference.goal_id,
        "creative_job_id": reference.creative_job_id,
        "creative_package_id": reference.creative_package_id,
        "shot_id": reference.shot_id,
        "creative_package_digest": reference.creative_package_digest,
        "input_relative_path": reference.input_relative_path,
        "sha256": reference.sha256,
        "bytes": reference.bytes,
        "source_reference": reference.source_reference,
        "source_digest": reference.source_digest,
        "rights_scope": _SCOPE,
    }
    if scope == expected:
        return  # Legacy exact per-shot approval: no batch semantics implied.
    # One explicit batch decision still persists independent immutable shot
    # scopes. This is NOT a blanket reusable image grant to unrelated shots.
    if not isinstance(scope, dict) or scope.get("schema_version") != "reference_consent_batch.v1":
        raise ValueError("REFERENCE_ASSET_APPROVAL_SCOPE_MISMATCH")
    shared = {
        "goal_id": reference.goal_id,
        "creative_job_id": reference.creative_job_id,
        "creative_package_id": reference.creative_package_id,
        "creative_package_digest": reference.creative_package_digest,
        "rights_scope": _SCOPE,
    }
    if any(scope.get(key) != value for key, value in shared.items()):
        raise ValueError("REFERENCE_ASSET_APPROVAL_SCOPE_MISMATCH")
    if scope.get("explicit_rights_attestation") is not True or scope.get(
        "byte_provenance"
    ) != "WINDOWS_CLIENT_CLAIM_NOT_CORE_HASHED":
        raise ValueError("REFERENCE_ASSET_APPROVAL_SCOPE_MISMATCH")
    refs = scope.get("references")
    if not isinstance(refs, list) or not 1 <= len(refs) <= 12 or scope.get("reference_count") != len(refs):
        raise ValueError("REFERENCE_ASSET_APPROVAL_SCOPE_MISMATCH")
    shot_ids = [item.get("shot_id") for item in refs if isinstance(item, dict)]
    asset_ids = [item.get("asset_id") for item in refs if isinstance(item, dict)]
    if (len(shot_ids) != len(refs) or len(set(shot_ids)) != len(refs)
        or len(set(asset_ids)) != len(refs)):
        raise ValueError("REFERENCE_ASSET_APPROVAL_SCOPE_MISMATCH")
    exact = {key: expected[key] for key in (
        "asset_id", "shot_id", "input_relative_path", "sha256", "bytes",
        "source_reference", "source_digest"
    )}
    if exact not in refs:
        raise ValueError("REFERENCE_ASSET_APPROVAL_SCOPE_MISMATCH")
