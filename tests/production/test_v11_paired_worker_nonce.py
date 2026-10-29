"""P0-Q2 #160: real Ed25519 Core key/nonce SQLite contract; I2V always held.

Synthetic key insertion is a *fixture only*, never evidence of real operator
approval, Windows signed process identity or filesystem/Comfy verification.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from picotoopet_core.db.database import Database
from picotoopet_core.security.worker_pairing import PairedWorkerTrust
from picotoopet_core.production.versioned_plan import (
    ProductionJobCreateV11Request, WorkerWitnessV11,
)
from test_reference_registration_api import (
    PACKAGE, _approve_batch, _v11_service, state as reference_state,
)
from test_v11_worker_witness import _witness


@pytest.fixture()
def paired(reference_state):
    db, registration, _, _, _ = reference_state
    approval = _approve_batch(reference_state)
    service = _v11_service(reference_state)
    job = service.create_job_v11(ProductionJobCreateV11Request(
        creative_package_id=PACKAGE,
        idempotency_key="paired-key-nonce-fake-unit-only",
        approved_reference_ids=[approval.approval_id],
    ))
    plan = service.get_plan(job.production_job_id)
    private = Ed25519PrivateKey.generate()
    pub = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    fingerprint = hashlib.sha256(pub).hexdigest()
    key_id = "wk-" + fingerprint[:40]
    executor = "windows-same-exe-worker"
    # ── Offline white-box fixture, NOT a production enrollment bypass or route.
    db.execute(
        "INSERT INTO production_worker_keys("
        "key_id,executor_id,public_key_hex,key_fingerprint,registered_by,"
        "operator_receipt_sha256,enrolled_at) VALUES (?,?,?,?,?,?,?)",
        (key_id, executor, pub.hex(), fingerprint, "TEST_FIXTURE_ONLY",
         "a" * 64, datetime.now(UTC).isoformat()),
    )
    trust = PairedWorkerTrust(db)
    return db, registration, service, job, plan, approval, private, key_id, trust


def signed(paired, **changes) -> WorkerWitnessV11:
    db, reg, service, job, plan, approval, private, key_id, trust = paired
    context = (db, reg, service, job, plan, approval)
    if "nonce" not in changes:
        changes["nonce"] = trust.issue_challenge(key_id, job.production_job_id,
                                                   "windows-same-exe-worker", job.plan_digest)
    t = datetime.now(UTC)
    data = _witness(context,
                    worker_key_id=key_id,
                    issued_at=t.isoformat(),
                    expires_at=(t + timedelta(seconds=15)).isoformat(),
                    **changes)
    unsigned = WorkerWitnessV11.model_validate(data)
    data["signature"] = private.sign(unsigned.signed_payload()).hex()
    return WorkerWitnessV11.model_validate(data)


def assert_no_execution(paired):
    db, _, _, job, _, _, _, _, _ = paired
    assert db.scalar("SELECT COUNT(*) FROM production_attempts WHERE production_job_id=?",
                     (job.production_job_id,)) == 0
    assert db.fetchone(
        "SELECT lease_token_digest FROM production_jobs WHERE production_job_id=?",
        (job.production_job_id,),
    )["lease_token_digest"] is None


def test_worker_trust_schema_idempotent_key_immutable_and_nonce_scoped(paired):
    db, _, _, job, _, _, _, key_id, trust = paired
    db.apply_migrations()
    assert db.scalar("SELECT COUNT(*) FROM schema_migrations WHERE version=25") == 0
    assert db.scalar("SELECT MAX(version) FROM schema_migrations") == 24
    nonce = trust.issue_challenge(key_id, job.production_job_id,
                                  "windows-same-exe-worker", job.plan_digest)
    row = db.fetchone("SELECT * FROM production_worker_challenges")
    assert row["nonce_digest"] == hashlib.sha256(nonce.encode()).hexdigest()
    assert row["nonce_digest"] != nonce
    assert row["production_job_id"] == job.production_job_id
    assert row["plan_digest"] == job.plan_digest
    with pytest.raises(ValueError, match="PRODUCTION_V11_CHALLENGE_ALREADY_ACTIVE"):
        trust.issue_challenge(key_id, job.production_job_id, "windows-same-exe-worker",
                              job.plan_digest)
    with pytest.raises(ValueError, match="PRODUCTION_V11_CHALLENGE_SCOPE_INVALID"):
        trust.issue_challenge(key_id, job.production_job_id, "windows-same-exe-worker",
                              "0" * 64)
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_KEY_UNTRUSTED"):
        trust.issue_challenge(key_id, job.production_job_id, "wrong-executor",
                              job.plan_digest)


def test_real_ed25519_signature_validates_but_production_claim_stays_closed(paired):
    db, _, service, job, _, _, _, _, trust = paired
    witness = signed(paired)
    with db.transaction() as connection:
        trust.verify_locked(connection, witness, redeem=False)
    with pytest.raises(ValueError, match="PRODUCTION_V11_WINDOWS_ATTESTATION_UNVERIFIED"):
        service.inspect_worker_witness_v11(job.production_job_id, witness)
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.claim(job.production_job_id, witness.executor_id)
    row = db.fetchone("SELECT consumed_at FROM production_worker_challenges")
    assert row["consumed_at"] is None
    assert_no_execution(paired)


def test_signature_forgery_and_unsigned_legacy_bearer_denied(paired):
    db, _, service, job, _, _, _, _, trust = paired
    witness = signed(paired)
    forged = witness.model_copy(update={"signature": "b" * 128})
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_SIGNATURE_INVALID"):
        service.inspect_worker_witness_v11(job.production_job_id, forged)
    # Modifying any canonical payload field invalidates its cryptographic signature.
    modified = witness.model_copy(update={"journal_digest": "0" * 64})
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_SIGNATURE_INVALID"):
        service.inspect_worker_witness_v11(job.production_job_id, modified)
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.claim(job.production_job_id, witness.executor_id)
    assert_no_execution(paired)


def test_unknown_key_wrong_executor_and_revoked_key_denied(paired):
    db, _, service, job, _, _, _, key_id, trust = paired
    witness = signed(paired)
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_KEY_UNTRUSTED"):
        service.inspect_worker_witness_v11(
            job.production_job_id, witness.model_copy(update={"worker_key_id": "unknown-worker-key-id"})
        )
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_KEY_UNTRUSTED"):
        service.inspect_worker_witness_v11(
            job.production_job_id, witness.model_copy(update={"executor_id": "other-worker"})
        )
    db.execute("UPDATE production_worker_keys SET revoked_at=? WHERE key_id=?",
               (datetime.now(UTC).isoformat(), key_id))
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_KEY_UNTRUSTED"):
        service.inspect_worker_witness_v11(job.production_job_id, witness)
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_KEY_UNTRUSTED"):
        trust.issue_challenge(key_id, job.production_job_id, "windows-same-exe-worker",
                              job.plan_digest)
    assert_no_execution(paired)


def test_spent_nonce_survives_database_reopen_and_blocks_replay(paired):
    db, _, service, job, _, _, _, _, trust = paired
    witness = signed(paired)
    with db.transaction() as connection:
        trust.verify_locked(connection, witness, redeem=True)
    assert db.scalar("SELECT COUNT(*) FROM production_worker_challenges WHERE consumed_at IS NOT NULL") == 1
    db.close()
    db.open()
    db.apply_migrations()
    with pytest.raises(ValueError, match="PRODUCTION_V11_WITNESS_CHALLENGE_INVALID"):
        with db.transaction() as connection:
            trust.verify_locked(connection, witness, redeem=True)
    with pytest.raises(ValueError, match="PRODUCTION_V11_WITNESS_CHALLENGE_INVALID"):
        service.inspect_worker_witness_v11(job.production_job_id, witness)
    assert_no_execution(paired)


def test_nonce_consumption_rolls_back_atomically_when_future_claim_fails(paired):
    db, _, service, job, _, _, _, _, trust = paired
    witness = signed(paired)
    with pytest.raises(ValueError, match="PRODUCTION_V11_WINDOWS_ATTESTATION_UNVERIFIED"):
        with db.transaction() as connection:
            service._audit_v11_core_before_lease(
                job.production_job_id, witness.executor_id, connection=connection
            )
            trust.verify_locked(connection, witness, redeem=True)
            raise ValueError("PRODUCTION_V11_WINDOWS_ATTESTATION_UNVERIFIED")
    assert db.scalar(
        "SELECT COUNT(*) FROM production_worker_challenges WHERE consumed_at IS NOT NULL"
    ) == 0
    with db.transaction() as connection:
        trust.verify_locked(connection, witness, redeem=True)
    with pytest.raises(ValueError, match="PRODUCTION_V11_WITNESS_CHALLENGE_INVALID"):
        with db.transaction() as connection:
            trust.verify_locked(connection, witness, redeem=True)
    assert_no_execution(paired)


@pytest.mark.parametrize("mutation", [
    {"nonce": "a" * 64},
    {"plan_digest": "b" * 64},
    {"production_job_id": "other-job"},
])
def test_challenge_scope_is_exact_and_forged_nonce_cannot_redeem(paired, mutation):
    db, _, service, job, _, _, private, _, trust = paired
    original = signed(paired)
    data = original.model_dump(mode="json")
    data.update(mutation)
    candidate = WorkerWitnessV11.model_validate(data)
    candidate = candidate.model_copy(
        update={"signature": private.sign(candidate.signed_payload()).hex()}
    )
    with pytest.raises(ValueError, match="PRODUCTION_V11_WITNESS_(CHALLENGE_INVALID|JOB_MISMATCH|PLAN_MISMATCH)"):
        service.inspect_worker_witness_v11(job.production_job_id, candidate)
    assert_no_execution(paired)


def test_nonce_timeout_and_approval_revocation_both_fail_closed(paired):
    db, registration, service, job, _, approval, _, _, trust = paired
    witness = signed(paired)
    db.execute("UPDATE production_worker_challenges SET issued_at=?,expires_at=?",
               ((datetime.now(UTC) - timedelta(seconds=45)).isoformat(),
                (datetime.now(UTC) - timedelta(seconds=5)).isoformat()))
    with pytest.raises(ValueError, match="PRODUCTION_V11_WITNESS_CHALLENGE_INVALID"):
        service.inspect_worker_witness_v11(job.production_job_id, witness)
    registration.revoke(
        approval.approval_id, request_digest=approval.approval_request_digest,
        reason="Synthetic owner revocation fixture",
    )
    with pytest.raises(ValueError, match="REFERENCE_ASSET_APPROVAL_NOT_VERIFIED"):
        service.inspect_worker_witness_v11(job.production_job_id, witness)
    assert_no_execution(paired)


def test_untrusted_bearer_has_no_enrollment_route_and_console_gate_denies_ci(paired):
    db, _, service, job, _, _, private, _, trust = paired
    pub = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    with pytest.raises(ValueError, match="PRODUCTION_V11_OPERATOR_CONSOLE_REQUIRED"):
        trust.enroll_from_local_console("test-executor", pub.hex())
    with pytest.raises(ValueError, match="PRODUCTION_V11_OPERATOR_CONSOLE_REQUIRED"):
        trust.revoke_from_local_console("synthetic-key")
    # public FastAPI production router exposes NO key enrollment or nonce minting.
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from picotoopet_core.api.routes import production
    from picotoopet_core.security.auth import require_auth

    app = FastAPI()
    app.include_router(production.router, prefix="/api/v1")
    app.state.services = SimpleNamespace(production=service)
    app.dependency_overrides[require_auth] = lambda: None
    with TestClient(app) as client:
        assert client.post("/api/v1/production/worker-keys/register",
                           json={"public_key_hex": pub.hex()}).status_code == 404
        assert client.post(f"/api/v1/production/jobs/{job.production_job_id}/challenge",
                           json={"executor_id": "windows-same-exe-worker"}).status_code == 404
    assert db.scalar("SELECT COUNT(*) FROM production_worker_keys") == 1
    assert_no_execution(paired)
