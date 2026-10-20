"""Authenticated, durable reference-asset batch *requests* over existing approvals.

One explicit user confirmation requests one pending resource approval containing
separate exact per-shot scopes. This does not inspect the Windows bytes or authorize
I2V GPU work; Windows must verify its immutable managed snapshot later.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from picotoopet_core.approvals.service import ApprovalError, ApprovalService
from picotoopet_core.db.database import Database
from picotoopet_core.handoffs.approvals import HandoffApprovalService

_TYPE = "production.reference_asset.v1"
_USE = "wan22.i2v.production.v1"


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


class ReferenceCandidateV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    shot_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    input_relative_path: str = Field(min_length=1, max_length=300)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(gt=0, le=32 * 1024 * 1024)
    source_reference: Literal["USER_SUPPLIED", "LICENSED"]
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rights_scope: Literal["wan22.i2v.production.v1"]

    @model_validator(mode="after")
    def _managed_path(self) -> ReferenceCandidateV1:
        path = self.input_relative_path
        parts = path.split("/")
        if (not path.startswith("PicotooPet/references/")
            or "\\" in path or ":" in path or path.endswith(".")
            or any(part in ("", ".", "..") or part.endswith((" ", ".")) for part in parts)
            or len(parts) < 3 or not path.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            or PurePosixPath(path).is_absolute()):
            raise ValueError("REFERENCE_MANAGED_PATH_INVALID")
        return self


class ReferenceBatchRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["reference_batch.v1"] = "reference_batch.v1"
    goal_id: str = Field(min_length=1, max_length=128)
    creative_package_id: str = Field(min_length=1, max_length=128)
    creative_package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_references: list[ReferenceCandidateV1] = Field(min_length=1, max_length=12)
    user_confirms_preview_and_rights: Literal[True]
    expires_seconds: int = Field(default=1800, ge=60, le=3600)

    @model_validator(mode="after")
    def _no_ambiguous_shot_or_path(self) -> ReferenceBatchRequestV1:
        shots = [x.shot_id for x in self.selected_references]
        paths = [x.input_relative_path.lower() for x in self.selected_references]
        if len(set(shots)) != len(shots) or len(set(paths)) != len(paths):
            raise ValueError("REFERENCE_BATCH_DUPLICATE_SHOT_OR_PATH")
        return self


class RegisteredReferenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    asset_id: str
    shot_id: str
    input_relative_path: str
    sha256: str
    bytes: int
    source_reference: str
    source_digest: str


class ReferenceBatchReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["reference_batch.v1"]
    batch_id: str
    approval_id: str
    approval_request_digest: str
    status: str
    expires_at: datetime
    creative_package_id: str
    creative_package_digest: str
    goal_id: str
    references: list[RegisteredReferenceV1]


class ReferenceRegistrationService:
    """No new tables. One SQLite IMMEDIATE transaction -> one atomic batch grant request."""

    def __init__(self, database: Database, approvals: HandoffApprovalService):
        self.database = database
        self.approvals = approvals

    @staticmethod
    def _receipt(row: object) -> ReferenceBatchReceiptV1:
        if row is None or row["approval_type"] != _TYPE or row["task_id"] is not None:
            raise ApprovalError("REFERENCE_BATCH_NOT_FOUND")
        scope = json.loads(row["scope_json"])
        if scope.get("schema_version") != "reference_consent_batch.v1":
            raise ApprovalError("REFERENCE_BATCH_NOT_FOUND")
        return ReferenceBatchReceiptV1(
            schema_version="reference_batch.v1",
            batch_id=scope["batch_id"], approval_id=row["approval_id"],
            approval_request_digest=ApprovalService._request_digest(row),
            status=row["status"], expires_at=datetime.fromisoformat(row["expires_at"]),
            creative_package_id=scope["creative_package_id"],
            creative_package_digest=scope["creative_package_digest"],
            goal_id=scope["goal_id"],
            references=[RegisteredReferenceV1.model_validate(item) for item in scope["references"]],
        )

    def get(self, approval_id: str) -> ReferenceBatchReceiptV1:
        return self._receipt(self.database.fetchone(
            "SELECT * FROM approvals WHERE approval_id=?", (approval_id,)
        ))

    def register(self, request: ReferenceBatchRequestV1, *, idempotency_key: str) -> ReferenceBatchReceiptV1:
        if not 1 <= len(idempotency_key) <= 200 or not idempotency_key.strip():
            raise ApprovalError("REFERENCE_IDEMPOTENCY_KEY_REQUIRED")
        try:
            UUID(request.goal_id)
            UUID(request.creative_package_id)
        except ValueError as error:
            raise ApprovalError("REFERENCE_SOURCE_ID_INVALID") from error

        key_digest = _digest({"key": idempotency_key})
        fingerprint = _digest(request.model_dump(mode="json", exclude={"selected_references"})
                              | {"selected_references": [
                                  x.model_dump(mode="json") for x in sorted(
                                      request.selected_references, key=lambda i: i.shot_id
                                  )
                              ]})
        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            # Lookup and insert are under ONE IMMEDIATE lock: no duplicate approvals
            # even when two API requests race or worker restarts between responses.
            existing = connection.execute(
                "SELECT * FROM approvals WHERE approval_type=? "
                "AND json_extract(scope_json, '$.batch_key_digest')=?",
                (_TYPE, key_digest),
            ).fetchone()
            if existing is not None:
                scope = json.loads(existing["scope_json"])
                if not hmac.compare_digest(scope.get("request_fingerprint", ""), fingerprint):
                    raise ApprovalError("REFERENCE_IDEMPOTENCY_CONFLICT")
                return self._receipt(existing)

            package = connection.execute(
                "SELECT * FROM creative_packages WHERE creative_package_id=?",
                (request.creative_package_id,),
            ).fetchone()
            if (package is None or package["quality_outcome"] != "PASS"
                or package["package_digest"] != request.creative_package_digest):
                raise ApprovalError("REFERENCE_CREATIVE_PACKAGE_NOT_FROZEN")
            lineage = connection.execute(
                "SELECT s.goal_id,s.creative_job_id,j.project_key,j.status "
                "FROM creative_goal_source_sets s JOIN creative_jobs j "
                "ON j.creative_job_id=s.creative_job_id "
                "WHERE s.creative_job_id=?", (package["creative_job_id"],)
            ).fetchone()
            if (lineage is None or lineage["goal_id"] != request.goal_id
                or lineage["status"] != "creative_ready"
                or lineage["project_key"] != f"goal-{request.goal_id}"):
                raise ApprovalError("REFERENCE_GOAL_CREATIVE_LINEAGE_MISMATCH")
            manifest = json.loads(package["manifest_json"])
            if (manifest.get("creative_job_id") != lineage["creative_job_id"]
                or manifest.get("creative_package_id") != package["creative_package_id"]
                or manifest.get("quality_outcome") != "PASS"
                or manifest.get("source_set_digest") != package["source_set_digest"]):
                raise ApprovalError("REFERENCE_CREATIVE_MANIFEST_INVALID")
            plan = manifest.get("stage_results", {}).get("shot_plan.v1", {})
            shots = plan.get("shots", []) if isinstance(plan, dict) else []
            eligible = {item.get("shot_id") for item in shots
                        if isinstance(item, dict) and item.get("render_intent") == "IMAGE_TO_VIDEO"}
            if any(item.shot_id not in eligible for item in request.selected_references):
                raise ApprovalError("REFERENCE_SHOT_NOT_I2V_OR_NOT_IN_PACKAGE")

            references = [
                RegisteredReferenceV1(
                    asset_id=str(uuid4()), **item.model_dump(exclude={"rights_scope"})
                ).model_dump(mode="json")
                for item in sorted(request.selected_references, key=lambda i: i.shot_id)
            ]
            scope = {
                "schema_version": "reference_consent_batch.v1",
                "batch_id": str(uuid4()),
                "batch_key_digest": key_digest,
                "request_fingerprint": fingerprint,
                "goal_id": request.goal_id,
                "creative_job_id": package["creative_job_id"],
                "creative_package_id": request.creative_package_id,
                "creative_package_digest": request.creative_package_digest,
                "rights_scope": _USE,
                "explicit_rights_attestation": True,
                "byte_provenance": "WINDOWS_CLIENT_CLAIM_NOT_CORE_HASHED",
                "reference_count": len(references),
                "shot_ids": ",".join(item["shot_id"] for item in references),
                "references": references,
            }
            grant = self.approvals.request_resource_in_transaction(
                connection, approval_type=_TYPE, scope=scope, requested_by="authenticated-reference-api",
                expires_at=now + timedelta(seconds=request.expires_seconds), requested_at=now,
            )
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id=?", (grant.approval_id,)
            ).fetchone()
            return self._receipt(row)

    def revoke(self, approval_id: str, *, request_digest: str, reason: str) -> ReferenceBatchReceiptV1:
        if not reason.strip() or len(reason) > 500:
            raise ApprovalError("REFERENCE_REVOCATION_REASON_REQUIRED")
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id=?", (approval_id,)
            ).fetchone()
            self._receipt(row)
            if not hmac.compare_digest(ApprovalService._request_digest(row), request_digest):
                raise ApprovalError("REFERENCE_APPROVAL_DIGEST_MISMATCH")
            if row["status"] not in ("Pending", "Approved", "Revoked"):
                raise ApprovalError("REFERENCE_APPROVAL_TERMINAL_CONFLICT")
            if row["status"] != "Revoked":
                connection.execute(
                    "UPDATE approvals SET status='Revoked',resolved_by=?,resolved_at=?,decision_reason=? "
                    "WHERE approval_id=?",
                    ("owner", datetime.now(UTC).isoformat(), reason.strip(), approval_id),
                )
            updated = connection.execute(
                "SELECT * FROM approvals WHERE approval_id=?", (approval_id,)
            ).fetchone()
            return self._receipt(updated)
