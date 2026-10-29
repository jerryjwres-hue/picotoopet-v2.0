"""P0-Q2 #155: native SQLite/HTTP Worker witness negative admission.

A fixture signature is deliberately NOT a trusted Windows same-EXE identity.
No GPU work, nonce redemption, or production lease can result from these tests.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from picotoopet_core.api.errors import install_error_handlers
from picotoopet_core.api.routes import production
from picotoopet_core.production.versioned_plan import (
    ProductionJobCreateV11Request, WorkerWitnessV11,
)
from picotoopet_core.security.auth import require_auth

from test_reference_registration_api import (
    PACKAGE, _approve_batch, _v11_service, state as reference_state,
)


@pytest.fixture()
def case(reference_state):
    db, registration, _, _, _ = reference_state
    approval = _approve_batch(reference_state)
    service = _v11_service(reference_state)
    job = service.create_job_v11(ProductionJobCreateV11Request(
        creative_package_id=PACKAGE,
        idempotency_key="v11-authenticated-worker-witness-test",
        approved_reference_ids=[approval.approval_id],
    ))
    plan = service.get_plan(job.production_job_id)
    return db, registration, service, job, plan, approval


def _witness(case, **changes):
    _, _, _, job, plan, _ = case
    start = datetime.now(UTC)
    refs = []
    for task in plan.tasks:
        ref = task.reference_asset
        if ref is None:
            continue
        refs.append({
            "production_task_id": task.production_task_id,
            "shot_id": task.shot_id,
            "asset_id": ref.asset_id,
            "approval_id": ref.approval_id,
            "approval_request_digest": ref.approval_request_digest,
            "source_sha256": ref.sha256,
            "source_bytes": ref.bytes,
            "source_relative_path": ref.input_relative_path,
            "snapshot_sha256": ref.sha256,
            "snapshot_bytes": ref.bytes,
            "snapshot_receipt_sha256": "d" * 64,
            "graph_digest": "e" * 64,
            "snapshot_relative_path": f"PicotooPet/snapshots/{task.production_task_id}/frame.png",
        })
    data = {
        "schema_version": "production.worker_witness.v1",
        "algorithm": "ed25519",
        "worker_key_id": "synthetic-unpinned-worker-key",
        "executor_id": "windows-same-exe-worker",
        "production_job_id": job.production_job_id,
        "plan_digest": job.plan_digest,
        "issued_at": start.isoformat(),
        "expires_at": (start + timedelta(seconds=20)).isoformat(),
        "nonce": "a" * 64,
        "worker_executable_sha256": "f" * 64,
        "journal_digest": "c" * 64,
        "journal_generation": 1,
        "journal_state": "NO_PRIOR_POST",
        "references": refs,
        "signature": "b" * 128,
    }
    data.update(changes)
    return data


def _parsed(data):
    return WorkerWitnessV11.model_validate_json(json.dumps(data))


def _no_new_gpu_facts(case):
    db, _, _, job, _, _ = case
    assert db.scalar(
        "SELECT COUNT(*) FROM production_attempts WHERE production_job_id=?",
        (job.production_job_id,),
    ) == 0
    state = db.fetchone(
        "SELECT lease_token_digest,lease_executor_id,status FROM production_jobs "
        "WHERE production_job_id=?", (job.production_job_id,),
    )
    assert state["lease_token_digest"] is None
    assert state["lease_executor_id"] is None
    assert state["status"] == job.status.value


def test_structurally_complete_signed_looking_witness_is_not_a_trusted_worker(case):
    _, _, service, job, _, _ = case
    proof = _parsed(_witness(case))
    for _ in range(2):
        with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_IDENTITY_NOT_PROVISIONED"):
            service.inspect_worker_witness_v11(job.production_job_id, proof)
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.claim(job.production_job_id, proof.executor_id)
    _no_new_gpu_facts(case)


@pytest.mark.parametrize("change,error", [
    ({"production_job_id": "wrong-job"}, "PRODUCTION_V11_WITNESS_JOB_MISMATCH"),
    ({"plan_digest": "0" * 64}, "PRODUCTION_V11_WITNESS_PLAN_MISMATCH"),
    ({"journal_state": "UNCERTAIN"}, "PRODUCTION_V11_WITNESS_POST_UNCERTAIN"),
])
def test_wrong_job_plan_or_unreconciled_comfy_never_admitted(case, change, error):
    _, _, service, job, _, _ = case
    with pytest.raises(ValueError, match=error):
        service.inspect_worker_witness_v11(job.production_job_id, _parsed(_witness(case, **change)))
    _no_new_gpu_facts(case)


@pytest.mark.parametrize("field,value", [
    ("shot_id", "shot-elsewhere"),
    ("production_task_id", "task-elsewhere"),
    ("asset_id", "asset-elsewhere"),
    ("approval_id", "approval-elsewhere"),
    ("approval_request_digest", "0" * 64),
    ("source_sha256", "0" * 64),
    ("source_bytes", 19),
    ("source_relative_path", "PicotooPet/references/wrong.png"),
    ("snapshot_sha256", "0" * 64),
    ("snapshot_bytes", 100),
])
def test_every_identity_and_byte_mismatch_rejected(case, field, value):
    _, _, service, job, _, _ = case
    data = _witness(case)
    data["references"][0][field] = value
    with pytest.raises(ValueError, match="PRODUCTION_V11_WITNESS_(ASSET_MISMATCH|TASK_COVERAGE_INVALID)"):
        service.inspect_worker_witness_v11(job.production_job_id, _parsed(data))
    _no_new_gpu_facts(case)


@pytest.mark.parametrize("field,value", [
    ("snapshot_receipt_sha256", "0" * 64),
    ("graph_digest", "0" * 64),
    ("snapshot_relative_path", "../escape.png"),
    ("snapshot_relative_path", "PicotooPet/../escape.png"),
])
def test_non_durable_or_unsafe_claimed_snapshot_never_admitted(case, field, value):
    _, _, service, job, _, _ = case
    data = _witness(case)
    data["references"][0][field] = value
    with pytest.raises(ValueError, match="PRODUCTION_V11_WITNESS_SNAPSHOT_INVALID"):
        service.inspect_worker_witness_v11(job.production_job_id, _parsed(data))
    _no_new_gpu_facts(case)


def test_missing_and_duplicate_reference_coverage(case):
    _, _, service, job, _, _ = case
    missing = _witness(case)
    missing["references"].pop()
    with pytest.raises(ValueError, match="PRODUCTION_V11_WITNESS_TASK_COVERAGE_INVALID"):
        service.inspect_worker_witness_v11(job.production_job_id, _parsed(missing))
    duplicates = _witness(case)
    duplicates["references"].append(dict(duplicates["references"][0]))
    with pytest.raises(ValueError, match="PRODUCTION_V11_WITNESS_DUPLICATE_REFERENCE"):
        _parsed(duplicates)
    _no_new_gpu_facts(case)


@pytest.mark.parametrize("minutes,expected", [
    (-10, "PRODUCTION_V11_WITNESS_STALE"),
    (10, "PRODUCTION_V11_WITNESS_STALE"),
])
def test_stale_or_future_signed_looking_witness_rejected(case, minutes, expected):
    _, _, service, job, _, _ = case
    issued = datetime.now(UTC) + timedelta(minutes=minutes)
    with pytest.raises(ValueError, match=expected):
        service.inspect_worker_witness_v11(
            job.production_job_id,
            _parsed(_witness(case,
                            issued_at=issued.isoformat(),
                            expires_at=(issued + timedelta(seconds=20)).isoformat())),
        )
    _no_new_gpu_facts(case)


@pytest.mark.parametrize("change", [
    {"nonce": "0" * 64},
    {"signature": "0" * 128},
    {"worker_executable_sha256": "0" * 64},
])
def test_placeholder_cryptographic_fields_rejected(case, change):
    with pytest.raises(ValueError, match="PRODUCTION_V11_WITNESS_PLACEHOLDER_REJECTED"):
        _parsed(_witness(case, **change))


def test_expired_and_revoked_approval_checked_in_locked_sqlite(case):
    db, registration, service, job, _, approval = case
    proof = _parsed(_witness(case))
    registration.revoke(
        approval.approval_id, request_digest=approval.approval_request_digest,
        reason="owner revocation",
    )
    with pytest.raises(ValueError, match="REFERENCE_ASSET_APPROVAL_NOT_VERIFIED"):
        service.inspect_worker_witness_v11(job.production_job_id, proof)
    _no_new_gpu_facts(case)
    # A synthetic DB change cannot recreate trusted Windows authority.
    db.execute("UPDATE approvals SET status='Approved',expires_at=? WHERE approval_id=?",
               ((datetime.now(UTC) - timedelta(seconds=5)).isoformat(), approval.approval_id))
    with pytest.raises(ValueError, match="REFERENCE_ASSET_APPROVAL_NOT_VERIFIED"):
        service.inspect_worker_witness_v11(job.production_job_id, proof)
    _no_new_gpu_facts(case)


def test_active_competing_lease_denies_witness_even_if_client_signed(case):
    db, _, service, job, _, _ = case
    db.execute("UPDATE production_jobs SET lease_executor_id=?,lease_token_digest=?,lease_expires_at=? "
               "WHERE production_job_id=?",
               ("other-worker", "a" * 64,
                (datetime.now(UTC) + timedelta(minutes=1)).isoformat(), job.production_job_id))
    with pytest.raises(ValueError, match="PRODUCTION_V11_WITNESS_LEASE_CONFLICT"):
        service.inspect_worker_witness_v11(job.production_job_id, _parsed(_witness(case)))
    assert db.scalar("SELECT COUNT(*) FROM production_attempts WHERE production_job_id=?",
                     (job.production_job_id,)) == 0


def test_unknown_post_and_journal_replay_never_allocate_second_attempt(case):
    db, _, service, job, plan, _ = case
    task = plan.tasks[0]
    timestamp = datetime.now(UTC).isoformat()
    db.execute(
        "INSERT INTO production_attempts("
        "production_attempt_id,production_job_id,production_task_id,attempt_number,"
        "executor_id,comfy_prompt_id,status,started_at) VALUES (?,?,?,?,?,?,?,?)",
        ("synthetic", job.production_job_id, task.production_task_id, 1,
         "windows-same-exe-worker", "old-prompt", "Running", timestamp),
    )
    db.execute(
        "UPDATE production_tasks SET status='Running',attempt_count=1,comfy_prompt_id=? "
        "WHERE production_task_id=?", ("old-prompt", task.production_task_id),
    )
    with pytest.raises(ValueError, match="PRODUCTION_V11_WITNESS_JOURNAL_MISMATCH"):
        service.inspect_worker_witness_v11(job.production_job_id, _parsed(_witness(case)))
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_IDENTITY_NOT_PROVISIONED"):
        service.inspect_worker_witness_v11(job.production_job_id, _parsed(_witness(
            case, journal_state="BOUND_RECOVERY"
        )))
    with pytest.raises(ValueError, match="PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"):
        service.claim(job.production_job_id, "windows-same-exe-worker")
    assert db.scalar("SELECT COUNT(*) FROM production_attempts WHERE production_job_id=?",
                     (job.production_job_id,)) == 1


def test_http_bearer_and_forged_signatures_never_issue_claim(case):
    db, _, service, job, _, _ = case
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(production.router, prefix="/api/v1")
    app.state.services = SimpleNamespace(production=service)
    app.dependency_overrides[require_auth] = lambda: None  # existing bearer is NOT Worker proof
    root = f"/api/v1/production/jobs/{job.production_job_id}"
    data = _witness(case)
    with TestClient(app) as client:
        for _ in range(2):
            response = client.post(f"{root}/witness/preflight", json=data)
            assert response.status_code == 409
            assert response.json()["error"]["code"] == "PRODUCTION_V11_WORKER_IDENTITY_NOT_PROVISIONED"
        # Normal /claim doesn't accept an added witness/signature/boolean.
        forged = client.post(f"{root}/claim", json={
            "executor_id": data["executor_id"], "verified": True, "witness": data,
        })
        assert forged.status_code == 422
        assert client.post(f"{root}/claim", json={
            "executor_id": data["executor_id"]
        }).status_code == 409
        assert client.post(f"{root}/witness/preflight", json={
            **data, "verified": True
        }).status_code == 422
        assert client.post(f"{root}/witness/preflight", json={
            **data, "signature": "0" * 128
        }).status_code == 422
    _no_new_gpu_facts(case)


def test_domain_separated_signed_payload_covers_all_mutable_claim_fields(case):
    original = _parsed(_witness(case))
    assert original.signed_payload().startswith(b"picotoopet.production.worker_witness.v1")
    assert b'"signature"' not in original.signed_payload()
    change = _parsed(_witness(case, journal_digest="1" * 64))
    assert original.signed_payload() != change.signed_payload()
    changed_signature = _parsed(_witness(case, signature="a" * 128))
    # Signature itself must not be part of the canonical signed bytes.
    # Issued-at is nondeterministic in _witness: normalize both for this comparison.
    assert b'"signature"' not in changed_signature.signed_payload()
