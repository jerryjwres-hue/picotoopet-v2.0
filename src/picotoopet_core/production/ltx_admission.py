"""Explicit LTX signed first-attempt admission; existing Core trust and SQL tables.

No engine is invoked here. Only the dedicated LTX worker may use this contract.
The legacy Wan parser and lease endpoints remain closed to v1.2.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.security.worker_pairing import PairedWorkerTrust
from .ltx_plan import LtxPilotPlanV12, compile_ltx_pilot_plan, load_frozen_ltx_pilot_plan
from .operator_trusted_host import require_b_key_locked
from .service import ProductionService
from .versioned_plan import WorkerWitnessV11


class LtxWorkerWitnessV12(WorkerWitnessV11):
    """Same paired Ed25519 key, different signature domain and renderer intent."""

    schema_version: Literal["production.ltx.worker_witness.v1"] = "production.ltx.worker_witness.v1"

    def signed_payload(self) -> bytes:
        # 01. A Wan witness must never be accepted as an LTX witness.
        fields = self.model_dump(mode="json", exclude={"signature"})
        return (b"picotoopet.production.ltx.worker_witness.v1\n"
                + json.dumps(fields, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8"))


class LtxClaimReceiptV12(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["production.ltx.claim.v1"] = "production.ltx.claim.v1"
    production_job_id: str
    production_task_id: str
    production_attempt_id: str
    executor_id: str
    lease_token: str
    lease_expires_at: datetime
    plan_digest: str
    vendor_intent_digest: str
    plan: LtxPilotPlanV12


def vendor_intent_digest(plan: LtxPilotPlanV12) -> str:
    """Bind the exact pre-upload vendor request and approved source bytes."""
    # 02. The source is the Core Creative Package, NOT a fabricated StoryPack
    #     digest. The actual vendor assetId is bound after image upload.
    return ProductionService._digest({
        "engine": plan.workflow_id,
        "creative_package_digest": plan.creative_package_digest,
        "first_frame_sha256": plan.reference_asset.sha256,
        "vendor_request": {
            "params": {
                "prompt": plan.prompt, "model": plan.model,
                "resolution": plan.resolution, "aspectRatio": plan.aspect_ratio,
                "duration": plan.duration_seconds, "fps": plan.fps,
                "seed": plan.seed, "cameraMotion": "none",
                "negativePrompt": "", "promptProvenance": "typed",
            },
            "inputs": {"startFrame": {"assetId": None}},
            "contract_version": 1,
        },
    })


def _audit_untouched(service: ProductionService, connection, job_id: str,
                     executor_id: str, plan_digest: str) -> LtxPilotPlanV12:
    # 03. Freeze, current Owner decision, ZIP and dynamic-film review are
    #     revalidated in the same IMMEDIATE transaction as nonce/claim.
    plan = load_frozen_ltx_pilot_plan(service, job_id)
    row = connection.execute(
        "SELECT * FROM production_jobs WHERE production_job_id=?", (job_id,),
    ).fetchone()
    if (row["status"] != "NeedsHuman"
        or row["failure_code"] != "LTX_SIGNED_WORKER_NOT_ENABLED"
        or row["lease_token_digest"] is not None
        or row["plan_digest"] != plan_digest):
        raise ValueError("LTX_CLAIM_NOT_UNTOUCHED")
    current = compile_ltx_pilot_plan(
        service, production_job_id=job_id,
        creative_package_id=plan.creative_package_id,
        approved_reference_id=plan.reference_asset.approval_id,
    )
    if current != plan or current.digest() != plan_digest:
        raise ValueError("LTX_CLAIM_FROZEN_SOURCE_CHANGED")
    for table in ("production_tasks", "production_attempts"):
        if connection.execute(
            f"SELECT 1 FROM {table} WHERE production_job_id=? LIMIT 1", (job_id,),
        ).fetchone() is not None:
            raise ValueError("LTX_CLAIM_PRIOR_ATTEMPT_UNCERTAIN")
    # An unresolved reservation for this executor must not be bypassed by
    # selecting another LTX job after its lease expires.
    if connection.execute(
        "SELECT 1 FROM production_jobs WHERE production_job_id<>? AND lease_executor_id=? "
        "AND (lease_expires_at>? OR (production_profile=? AND status='Rendering')) LIMIT 1",
        (job_id, executor_id, datetime.now(UTC).isoformat(), plan.production_profile),
    ).fetchone() is not None:
        raise ValueError("LTX_CLAIM_EXECUTOR_BUSY")
    return plan


def issue_ltx_challenge(service: ProductionService, job_id: str, key_id: str,
                        executor_id: str, plan_digest: str) -> tuple[str, datetime, datetime]:
    # 04. Reuse the enrolled key and bounded, one-use challenge table.
    db = service.repository.database
    with db.transaction() as connection:
        _audit_untouched(service, connection, job_id, executor_id, plan_digest)
        require_b_key_locked(connection, key_id, executor_id)
        nonce = PairedWorkerTrust(db).issue_challenge(
            key_id, job_id, executor_id, plan_digest, connection=connection,
            plan_schema_version="1.2",
        )
        row = connection.execute(
            "SELECT issued_at,expires_at FROM production_worker_challenges WHERE nonce_digest=?",
            (hashlib.sha256(nonce.encode("ascii")).hexdigest(),),
        ).fetchone()
        return nonce, datetime.fromisoformat(row["issued_at"]), datetime.fromisoformat(row["expires_at"])


def claim_ltx_first_attempt(service: ProductionService, job_id: str,
                            witness: LtxWorkerWitnessV12) -> LtxClaimReceiptV12:
    """Atomically consume one signed nonce and reserve exactly one attempt."""
    db = service.repository.database
    with db.transaction() as connection:
        plan = _audit_untouched(service, connection, job_id, witness.executor_id, witness.plan_digest)
        if (witness.production_job_id != job_id or witness.journal_state != "NO_PRIOR_POST"
            or len(witness.references) != 1 or witness.journal_digest == "0" * 64):
            raise ValueError("LTX_CLAIM_WITNESS_SCOPE_MISMATCH")
        ref, observed = plan.reference_asset, witness.references[0]
        intent = vendor_intent_digest(plan)
        if (
            observed.production_task_id != plan.production_task_id
            or observed.shot_id != plan.shot_id or observed.asset_id != ref.asset_id
            or observed.approval_id != ref.approval_id
            or observed.approval_request_digest != ref.approval_request_digest
            or observed.source_sha256 != ref.sha256 or observed.source_bytes != ref.bytes
            or observed.source_relative_path != ref.input_relative_path
            or observed.snapshot_sha256 != ref.sha256 or observed.snapshot_bytes != ref.bytes
            or observed.snapshot_receipt_sha256 == "0" * 64
            or observed.graph_digest != intent
            or not observed.snapshot_relative_path.startswith("PicotooPet/")
            or any(part in {"", ".", ".."} for part in observed.snapshot_relative_path.split("/"))
            or "\\" in observed.snapshot_relative_path or ":" in observed.snapshot_relative_path
        ):
            raise ValueError("LTX_CLAIM_REFERENCE_WITNESS_MISMATCH")
        require_b_key_locked(connection, witness.worker_key_id, witness.executor_id)

        # 05. Real Ed25519 + nonce redemption. All following writes roll back
        #     together on any failure. No retry of an uncertain reservation.
        PairedWorkerTrust(db).verify_locked(connection, witness, redeem=True)
        token = secrets.token_urlsafe(32)
        token_digest = hashlib.sha256(token.encode()).hexdigest()
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=600)
        stamp = now.isoformat()
        attempt_id = str(uuid4())
        witness_json = json.dumps(witness.model_dump(mode="json"), sort_keys=True,
                                  separators=(",", ":"), ensure_ascii=False)
        nonce_digest = hashlib.sha256(witness.nonce.encode("ascii")).hexdigest()
        result = connection.execute(
            "UPDATE production_worker_challenges SET admitted_lease_token_digest=?,"
            "admitted_witness_sha256=?,admitted_witness_json=? "
            "WHERE nonce_digest=? AND consumed_at IS NOT NULL AND admitted_lease_token_digest IS NULL",
            (token_digest, hashlib.sha256(witness_json.encode()).hexdigest(), witness_json, nonce_digest),
        )
        if result.rowcount != 1:
            raise ValueError("LTX_CLAIM_NONCE_REPLAY")

        # 06. Materialize a renderer-specific task snapshot in the existing
        #     lifecycle tables. Deliberately no Comfy prompt ID or video ID
        #     until an actual vendor receipt exists. Legacy parsers reject it.
        task_json = json.dumps(plan.model_dump(mode="json"), sort_keys=True,
                               separators=(",", ":"), ensure_ascii=False)
        connection.execute(
            "INSERT INTO production_tasks(production_task_id,production_job_id,shot_id,"
            "order_index,render_intent,execution_disposition,workflow_id,task_plan_json,"
            "status,attempt_count,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (plan.production_task_id, job_id, plan.shot_id, 1, "IMAGE_TO_VIDEO",
             "Executable", plan.workflow_id, task_json, "Running", 1, stamp, stamp),
        )
        connection.execute(
            "INSERT INTO production_attempts(production_attempt_id,production_job_id,"
            "production_task_id,attempt_number,executor_id,status,started_at) VALUES (?,?,?,?,?,?,?)",
            (attempt_id, job_id, plan.production_task_id, 1, witness.executor_id, "Running", stamp),
        )
        result = connection.execute(
            "UPDATE production_jobs SET status='Rendering',lease_executor_id=?,lease_token_digest=?,"
            "lease_expires_at=?,failure_code=NULL,finished_at=NULL,updated_at=? "
            "WHERE production_job_id=? AND status='NeedsHuman' AND lease_token_digest IS NULL",
            (witness.executor_id, token_digest, expires.isoformat(), stamp, job_id),
        )
        if result.rowcount != 1:
            raise ValueError("LTX_CLAIM_CONCURRENT_MUTATION")
        return LtxClaimReceiptV12(
            production_job_id=job_id, production_task_id=plan.production_task_id,
            production_attempt_id=attempt_id, executor_id=witness.executor_id,
            lease_token=token, lease_expires_at=expires, plan_digest=plan.digest(),
            vendor_intent_digest=intent, plan=plan,
        )
