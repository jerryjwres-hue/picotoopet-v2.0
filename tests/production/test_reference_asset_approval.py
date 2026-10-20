"""Only synthetic Core approval state; never implies a user granted image rights."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from picotoopet_core.approvals.service import ApprovalService
from picotoopet_core.db.database import Database
from picotoopet_core.production.reference_assets import (
    ReferenceAssetIdentityV1,
    approved_reference_descriptor,
    verify_persisted_reference_approval,
)


def _identity() -> ReferenceAssetIdentityV1:
    return ReferenceAssetIdentityV1(
        schema_version="reference_asset.v1",
        asset_id=str(uuid4()),
        goal_id="goal-1",
        creative_job_id="creative-1",
        creative_package_id="creative-package-1",
        production_job_id="job-1",
        production_task_id="task-1",
        shot_id="shot-1",
        creative_package_digest="a" * 64,
        input_relative_path="PicotooPet/references/shot-1.png",
        sha256="b" * 64,
        bytes=128,
        source_reference="user-selected-reference",
        source_digest="c" * 64,
        rights_scope="wan22.i2v.production.v1",
        approval_id=str(uuid4()),
        approval_request_digest="d" * 64,
    )


def _scope(r: ReferenceAssetIdentityV1) -> dict[str, str | int]:
    return {
        "asset_id": r.asset_id,
        "goal_id": r.goal_id,
        "creative_job_id": r.creative_job_id,
        "creative_package_id": r.creative_package_id,
        "shot_id": r.shot_id,
        "creative_package_digest": r.creative_package_digest,
        "input_relative_path": r.input_relative_path,
        "sha256": r.sha256,
        "bytes": r.bytes,
        "source_reference": r.source_reference,
        "source_digest": r.source_digest,
        "rights_scope": r.rights_scope,
    }


def _insert_fake_approval(db: Database, r: ReferenceAssetIdentityV1, *, status: str) -> str:
    now = datetime.now(UTC).isoformat()
    expires = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    db.execute(
        "INSERT INTO approvals (approval_id,task_id,approval_type,scope_json,status,token_hash,"
        "requested_by,expires_at,requested_at,resolved_by,resolved_at,decision_reason) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            r.approval_id,
            None,
            "production.reference_asset.v1",
            json.dumps(_scope(r), sort_keys=True),
            status,
            "z" * 64,
            "test-fake-request",
            expires,
            now,
            "synthetic-fixture-not-a-real-user" if status == "Approved" else None,
            now if status == "Approved" else None,
            "unit-test-only" if status == "Approved" else None,
        ),
    )
    row = db.fetchone("SELECT * FROM approvals WHERE approval_id=?", (r.approval_id,))
    assert row is not None
    return ApprovalService._request_digest(row)


def test_only_exact_existing_approved_reference_scope_is_accepted(tmp_path) -> None:
    db = Database(tmp_path / "ref-approval.sqlite3")
    db.open()
    db.apply_migrations()
    original = _identity()
    try:
        with pytest.raises(ValueError, match="REFERENCE_ASSET_APPROVAL_NOT_VERIFIED"):
            verify_persisted_reference_approval(db, original)
        request_digest = _insert_fake_approval(db, original, status="Pending")
        r = original.model_copy(update={"approval_request_digest": request_digest})
        with pytest.raises(ValueError, match="REFERENCE_ASSET_APPROVAL_NOT_VERIFIED"):
            verify_persisted_reference_approval(db, r)
        db.execute(
            "UPDATE approvals SET status=?,resolved_by=?,resolved_at=? WHERE approval_id=?",
            ("Approved", "synthetic-fixture-not-a-real-user", datetime.now(UTC).isoformat(), r.approval_id),
        )
        verify_persisted_reference_approval(db, r)
        descriptor = approved_reference_descriptor(db, r)
        assert descriptor.model_dump() == {
            "approval_id": r.approval_id,
            "shot_id": r.shot_id,
            "asset_id": r.asset_id,
            "relative_path": r.input_relative_path,
            "sha256": r.sha256,
            "byte_length": r.bytes,
        }

        for update in (
            {"shot_id": "shot-different"},
            {"asset_id": str(uuid4())},
            {"sha256": "e" * 64},
            {"source_digest": "f" * 64},
            {"bytes": 129},
            {"creative_package_id": "other-creative-package"},
            {"approval_request_digest": "f" * 64},
        ):
            mismatch = r.model_copy(update=update)
            with pytest.raises(ValueError, match="REFERENCE_ASSET_APPROVAL"):
                verify_persisted_reference_approval(db, mismatch)
        db.execute("UPDATE approvals SET status='Rejected' WHERE approval_id=?", (r.approval_id,))
        with pytest.raises(ValueError, match="REFERENCE_ASSET_APPROVAL_NOT_VERIFIED"):
            verify_persisted_reference_approval(db, r)
    finally:
        db.close()


def test_plain_path_cannot_be_approved_record() -> None:
    with pytest.raises(ValidationError):
        ReferenceAssetIdentityV1.model_validate({"input_relative_path": "photos/pet.png"})


def test_asset_id_cannot_be_a_path_hash_or_approval_id() -> None:
    original = _identity().model_dump()
    for malformed in ("photos/pet.png", "b" * 64, "asset-1", ""):
        with pytest.raises(ValidationError):
            ReferenceAssetIdentityV1.model_validate(
                dict(original, asset_id=malformed)
            )


def test_descriptor_does_not_mint_grant_without_persisted_approval(tmp_path) -> None:
    db = Database(tmp_path / "unapproved.sqlite3")
    db.open()
    db.apply_migrations()
    try:
        with pytest.raises(ValueError, match="REFERENCE_ASSET_APPROVAL_NOT_VERIFIED"):
            approved_reference_descriptor(db, _identity())
    finally:
        db.close()


def test_pending_approval_scope_cannot_claim_future_production_identity() -> None:
    """The plan must bind future production IDs; approval is only source/shot consent."""
    base = _identity()
    scope = _scope(base)
    assert "asset_id" in scope and "creative_package_digest" in scope
    assert "production_job_id" not in scope and "production_task_id" not in scope
    assert scope["shot_id"] == base.shot_id
