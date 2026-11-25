"""Explicit LTX signed first-attempt admission; existing Core trust and SQL tables.

No engine is invoked here. Only the dedicated LTX worker may use this contract.
The legacy Wan parser and lease endpoints remain closed to v1.2.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.security.worker_pairing import PairedWorkerTrust, _verify_ed25519
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


class LtxReferenceCheckV12(BaseModel):
    """Read-only exact snapshot authority; never grants a lease."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    vendor_intent_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class LtxReferenceReceiptV12(LtxReferenceCheckV12):
    schema_version: Literal["production.ltx.reference_check.v1"] = "production.ltx.reference_check.v1"
    plan: LtxPilotPlanV12


def check_ltx_reference(service: ProductionService, job_id: str,
                        request: LtxReferenceCheckV12) -> LtxReferenceReceiptV12:
    # 01. Reuse the compiler's live approval, source and frozen identity checks.
    #     Historical plan readback alone must never authorize a snapshot.
    with service.repository.database.transaction():
        plan = load_frozen_ltx_pilot_plan(service, job_id)
        current = compile_ltx_pilot_plan(
            service, production_job_id=job_id,
            creative_package_id=plan.creative_package_id,
            approved_reference_id=plan.reference_asset.approval_id,
        )
        if (current != plan or plan.digest() != request.plan_digest
                or vendor_intent_digest(plan) != request.vendor_intent_digest):
            raise ValueError("LTX_REFERENCE_CHECK_SCOPE_MISMATCH")
        return LtxReferenceReceiptV12(
            plan_digest=request.plan_digest,
            vendor_intent_digest=request.vendor_intent_digest, plan=plan,
        )


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


class LtxLeaseRequestV12(BaseModel):
    """Existing lease identity, never a new claim or attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    executor_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    lease_token: str = Field(min_length=1, max_length=200)
    production_attempt_id: str = Field(min_length=1, max_length=160)
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    vendor_intent_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class LtxLeaseReceiptV12(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["production.ltx.lease.v1"] = "production.ltx.lease.v1"
    production_job_id: str
    production_task_id: str
    production_attempt_id: str
    plan_digest: str
    vendor_intent_digest: str
    lease_expires_at: datetime


def check_ltx_lease(service: ProductionService, job_id: str,
                    request: LtxLeaseRequestV12, *, renew: bool = False) -> LtxLeaseReceiptV12:
    """Recheck the current signed reservation, optionally extend its lease.

    This does not bind a vendor result or establish that the local GPU has
    run. The Windows process must still own the shared GPU lock and journal.
    """
    with service.repository.database.transaction() as connection:
        return _check_ltx_lease_locked(service, connection, job_id, request, renew=renew)


def _check_ltx_lease_locked(service: ProductionService, connection, job_id: str,
                            request: LtxLeaseRequestV12, *, renew: bool = False) -> LtxLeaseReceiptV12:
    # 01. Source identity and current revocable approval are checked
    #     together with the actual persisted lease and task.
    plan = load_frozen_ltx_pilot_plan(service, job_id)
    job = connection.execute(
        "SELECT * FROM production_jobs WHERE production_job_id=?", (job_id,),
    ).fetchone()
    now = datetime.now(UTC)
    digest = hashlib.sha256(request.lease_token.encode()).hexdigest()
    if (job["status"] != "Rendering"
        or job["lease_executor_id"] != request.executor_id
        or not job["lease_token_digest"]
        or not hmac.compare_digest(job["lease_token_digest"], digest)
        or not job["lease_expires_at"]
        or datetime.fromisoformat(job["lease_expires_at"]) <= now
        or job["plan_digest"] != request.plan_digest
        or vendor_intent_digest(plan) != request.vendor_intent_digest):
        raise ValueError("LTX_LEASE_SCOPE_INVALID")
    current = compile_ltx_pilot_plan(
        service, production_job_id=job_id,
        creative_package_id=plan.creative_package_id,
        approved_reference_id=plan.reference_asset.approval_id,
    )
    if current != plan:
        raise ValueError("LTX_LEASE_SOURCE_CHANGED")

    # 02. A pasted token, rotated legacy lease, or tampered signed
    #     witness cannot create authority. Nonce expiry is evaluated
    #     at admission; later checks require the current admitted lease.
    row = connection.execute(
        "SELECT * FROM production_worker_challenges WHERE production_job_id=? "
        "AND admitted_lease_token_digest=? AND consumed_at IS NOT NULL",
        (job_id, digest),
    ).fetchone()
    if (row is None or row["executor_id"] != request.executor_id
        or row["plan_digest"] != plan.digest() or not row["admitted_witness_json"]
        or hashlib.sha256(row["admitted_witness_json"].encode()).hexdigest()
            != row["admitted_witness_sha256"]):
        raise ValueError("LTX_LEASE_SIGNED_ADMISSION_REQUIRED")
    proof = LtxWorkerWitnessV12.model_validate_json(row["admitted_witness_json"])
    if (proof.production_job_id != job_id or proof.plan_digest != plan.digest()
        or proof.executor_id != request.executor_id or proof.worker_key_id != row["key_id"]
        or hashlib.sha256(proof.nonce.encode("ascii")).hexdigest() != row["nonce_digest"]):
        raise ValueError("LTX_LEASE_SIGNED_ADMISSION_REQUIRED")
    key = require_b_key_locked(connection, proof.worker_key_id, proof.executor_id)
    _verify_ed25519(key["public_key_hex"], proof.signature, proof.signed_payload())

    # 03. Only the one immutable reserved LTX attempt may use the lease.
    tasks = connection.execute(
        "SELECT * FROM production_tasks WHERE production_job_id=?", (job_id,),
    ).fetchall()
    attempts = connection.execute(
        "SELECT * FROM production_attempts WHERE production_job_id=?", (job_id,),
    ).fetchall()
    if len(tasks) != 1 or len(attempts) != 1:
        raise ValueError("LTX_LEASE_ATTEMPT_SCOPE_INVALID")
    task, attempt = tasks[0], attempts[0]
    if (task["production_task_id"] != plan.production_task_id
        or task["workflow_id"] != plan.workflow_id or task["shot_id"] != plan.shot_id
        or task["status"] != "Running" or task["attempt_count"] != 1
        or json.loads(task["task_plan_json"]) != plan.model_dump(mode="json")
        or attempt["production_attempt_id"] != request.production_attempt_id
        or attempt["production_task_id"] != plan.production_task_id
        or attempt["attempt_number"] != 1 or attempt["status"] != "Running"
        or attempt["executor_id"] != request.executor_id
        or task["comfy_prompt_id"] is not None or attempt["comfy_prompt_id"] is not None):
        raise ValueError("LTX_LEASE_ATTEMPT_SCOPE_INVALID")
    # 04. A bound vendor receipt must be complete, never a legacy prompt ID.
    if (attempt["ltx_generation_id"] is None) != (attempt["ltx_start_frame_asset_id"] is None):
        raise ValueError("LTX_VENDOR_BINDING_INCOMPLETE")
    expires = datetime.fromisoformat(job["lease_expires_at"])
    if renew:
        # 04. Renew only the exact signed lease, with no task or attempt
        #     creation and no vendor request. Revoke stops renewal.
        expires = now + timedelta(seconds=600)
        connection.execute(
            "UPDATE production_jobs SET lease_expires_at=?,updated_at=? "
            "WHERE production_job_id=? AND lease_token_digest=?",
            (expires.isoformat(), now.isoformat(), job_id, digest),
        )
    return LtxLeaseReceiptV12(
        production_job_id=job_id, production_task_id=plan.production_task_id,
        production_attempt_id=request.production_attempt_id,
        plan_digest=plan.digest(), vendor_intent_digest=request.vendor_intent_digest,
        lease_expires_at=expires,
    )


class LtxVendorBindingRequestV12(LtxLeaseRequestV12):
    generation_id: UUID
    start_frame_asset_id: UUID


class LtxVendorBindingReceiptV12(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["production.ltx.vendor_binding.v1"] = "production.ltx.vendor_binding.v1"
    production_job_id: str
    production_task_id: str
    production_attempt_id: str
    plan_digest: str
    vendor_intent_digest: str
    generation_id: UUID
    start_frame_asset_id: UUID


def bind_ltx_vendor_generation(service: ProductionService, job_id: str,
                               request: LtxVendorBindingRequestV12) -> LtxVendorBindingReceiptV12:
    # 01. In the same transaction, revalidate signed lease and bind exactly
    #     one vendor generation. A receipt is not media success or local-lane proof.
    generation = str(request.generation_id)
    asset = str(request.start_frame_asset_id)
    if request.generation_id.int == 0 or request.start_frame_asset_id.int == 0:
        raise ValueError("LTX_VENDOR_BINDING_INVALID")
    with service.repository.database.transaction() as connection:
        lease = _check_ltx_lease_locked(service, connection, job_id, request)
        row = connection.execute(
            "SELECT ltx_generation_id,ltx_start_frame_asset_id FROM production_attempts "
            "WHERE production_attempt_id=?", (lease.production_attempt_id,),
        ).fetchone()
        prior = (row["ltx_generation_id"], row["ltx_start_frame_asset_id"])
        if prior != (None, None) and prior != (generation, asset):
            raise ValueError("LTX_VENDOR_BINDING_CONFLICT")
        if prior == (None, None):
            duplicate = connection.execute(
                "SELECT 1 FROM production_attempts WHERE ltx_generation_id=?", (generation,),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("LTX_VENDOR_GENERATION_ALREADY_BOUND")
            result = connection.execute(
                "UPDATE production_attempts SET ltx_generation_id=?,ltx_start_frame_asset_id=? "
                "WHERE production_attempt_id=? AND ltx_generation_id IS NULL "
                "AND ltx_start_frame_asset_id IS NULL",
                (generation, asset, lease.production_attempt_id),
            )
            if result.rowcount != 1:
                raise ValueError("LTX_VENDOR_BINDING_CONFLICT")
        return LtxVendorBindingReceiptV12(
            production_job_id=job_id, production_task_id=lease.production_task_id,
            production_attempt_id=lease.production_attempt_id,
            plan_digest=lease.plan_digest, vendor_intent_digest=lease.vendor_intent_digest,
            generation_id=request.generation_id, start_frame_asset_id=request.start_frame_asset_id,
        )
