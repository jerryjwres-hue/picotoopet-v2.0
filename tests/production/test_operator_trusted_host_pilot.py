"""Approved B: real disposable Ed25519/SQLite/HTTP admission, no live host/GPU.

Operator trust is explicitly seeded only in runner fixtures. These tests do not
claim hardware attestation or authorize enrollment on an owner's machine.
"""
from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from picotoopet_core.api.errors import install_error_handlers
from picotoopet_core.api.routes import production
from picotoopet_core.production.versioned_plan import WorkerWitnessV11
from picotoopet_core.security.auth import require_auth
from picotoopet_core.security import worker_pairing
from test_reference_registration_api import state as reference_state
from test_v11_paired_worker_nonce import paired, signed


MODEL = "OPERATOR_TRUSTED_PRIVATE_HOST_V1"


@pytest.fixture()
def pilot(paired):
    db, _, service, job, plan, _, _, key_id, _ = paired
    # On the frozen RED source there is no policy column yet: still exercise
    # the actual HTTP request so the primary RED is 422 versus required 200.
    columns = {row["name"] for row in db.fetchall("PRAGMA table_info(production_worker_keys)")}
    if "trust_model" in columns:
        db.execute("UPDATE production_worker_keys SET trust_model=? WHERE key_id=?", (MODEL, key_id))
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(production.router, prefix="/api/v1")
    app.state.services = SimpleNamespace(production=service)
    app.dependency_overrides[require_auth] = lambda: None
    root = f"/api/v1/production/jobs/{job.production_job_id}"
    task = next(task for task in plan.tasks if task.reference_asset is not None)
    return SimpleNamespace(paired=paired, db=db, service=service, job=job, task=task,
                           root=root, task_root=f"{root}/tasks/{task.production_task_id}", app=app)


def claim(client, p, witness=None):
    proof = witness or signed(p.paired)
    return client.post(f"{p.root}/claim", json={
        "executor_id": proof.executor_id, "worker_witness": proof.model_dump(mode="json"),
    })


def admit(client, p):
    response = claim(client, p)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan"]["schema_version"] == "1.1"
    assert body["lease_token"]
    return {"executor_id": body["executor_id"], "lease_token": body["lease_token"]}


def result(p, lease):
    return {**lease, "comfy_prompt_id": "fake-prompt", "output_relpath": "PicotooPet/output/fake.webm",
            "output_sha256": "b" * 64, "output_bytes": 1024, "mime_type": "video/webm",
            "width": p.task.width, "height": p.task.height,
            "frame_count": p.task.frame_count, "fps": p.task.fps}


def facts(p):
    return [tuple(row) for row in p.db.fetchall("SELECT * FROM production_jobs")], [
        tuple(row) for row in p.db.fetchall("SELECT * FROM production_tasks")], [
        tuple(row) for row in p.db.fetchall("SELECT * FROM production_attempts")]


def test_operator_trusted_signed_claim_admits_exactly_one_real_lease(pilot):
    p = pilot
    proof = signed(p.paired)
    with TestClient(p.app) as client:
        preflight = client.post(f"{p.root}/witness/preflight", json=proof.model_dump(mode="json"))
        assert preflight.status_code == 409
        assert p.db.scalar("SELECT COUNT(*) FROM production_worker_challenges WHERE consumed_at IS NOT NULL") == 0
        response = claim(client, p, proof)
        assert response.status_code == 200, response.text
        body = response.json()
        row = p.db.fetchone("SELECT * FROM production_jobs WHERE production_job_id=?", (p.job.production_job_id,))
        assert row["lease_token_digest"] == hashlib.sha256(body["lease_token"].encode()).hexdigest()
        assert row["lease_executor_id"] == proof.executor_id
        assert p.db.scalar("SELECT COUNT(*) FROM production_worker_challenges WHERE consumed_at IS NOT NULL") == 1
        original = facts(p)
        assert claim(client, p, proof).status_code == 409
        assert facts(p) == original


def test_legacy_claim_and_bearer_policy_selection_stay_denied(pilot):
    p = pilot
    with TestClient(p.app) as client:
        assert client.post(f"{p.root}/claim", json={"executor_id": "windows-same-exe-worker"}).status_code == 409
        proof = signed(p.paired)
        response = client.post(f"{p.root}/claim", json={
            "executor_id": proof.executor_id, "worker_witness": proof.model_dump(mode="json"),
            "trust_model": MODEL,
        })
        assert response.status_code == 422
    assert p.db.scalar("SELECT COUNT(*) FROM production_worker_challenges WHERE consumed_at IS NOT NULL") == 0


def test_existing_strict_key_cannot_authorize_b(paired):
    db, _, service, job, _, _, _, key_id, _ = paired
    columns = {row["name"] for row in db.fetchall("PRAGMA table_info(production_worker_keys)")}
    assert "trust_model" in columns
    assert db.fetchone("SELECT trust_model FROM production_worker_keys WHERE key_id=?", (key_id,))["trust_model"] != MODEL
    with pytest.raises(ValueError):
        service.claim(job.production_job_id, "windows-same-exe-worker", worker_witness=signed(paired))
    assert db.scalar("SELECT COUNT(*) FROM production_worker_challenges WHERE consumed_at IS NOT NULL") == 0


@pytest.mark.parametrize("change", [{"signature": "b" * 128}, {"nonce": "0" * 64},
    {"plan_digest": "0" * 64}, {"production_job_id": "wrong-job"},
    {"executor_id": "wrong-executor"}, {"journal_state": "UNCERTAIN"}])
def test_invalid_signed_claim_leaves_nonce_and_all_execution_facts_untouched(pilot, change):
    p = pilot
    proof = signed(p.paired)
    changed = proof.model_copy(update=change)
    if "signature" not in change:
        changed = changed.model_copy(update={"signature": p.paired[6].sign(changed.signed_payload()).hex()})
    original = facts(p)
    with TestClient(p.app) as client:
        response = claim(client, p, changed)
        assert response.status_code == 409, response.text
    assert facts(p) == original
    assert p.db.scalar("SELECT COUNT(*) FROM production_worker_challenges WHERE consumed_at IS NOT NULL") == 0


def test_claim_rollback_restores_nonce_if_lease_write_fails(pilot):
    p = pilot
    proof = signed(p.paired)
    original = facts(p)
    p.db.execute("CREATE TRIGGER fixture_abort_claim BEFORE UPDATE OF lease_token_digest ON production_jobs "
                 "WHEN NEW.lease_token_digest IS NOT NULL BEGIN SELECT RAISE(ABORT, 'fixture lease failure'); END")
    with TestClient(p.app, raise_server_exceptions=False) as client:
        assert claim(client, p, proof).status_code != 200
        assert facts(p) == original
        assert p.db.scalar("SELECT COUNT(*) FROM production_worker_challenges WHERE consumed_at IS NOT NULL") == 0
        p.db.execute("DROP TRIGGER fixture_abort_claim")
        assert claim(client, p, proof).status_code == 200


def test_concurrent_claims_redeem_once(pilot):
    p = pilot
    proof = signed(p.paired)
    with TestClient(p.app) as client:
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: claim(client, p, proof).status_code, range(4)))
    assert sorted(responses) == [200, 409, 409, 409]
    assert p.db.scalar("SELECT COUNT(*) FROM production_worker_challenges WHERE consumed_at IS NOT NULL") == 1


@pytest.mark.parametrize("revoke", ["key", "approval", "lease"])
@pytest.mark.parametrize("operation", ["heartbeat", "reserve", "bind", "result", "failure"])
def test_each_mutation_requires_current_admitted_lease_active_key_and_approval(pilot, revoke, operation):
    p = pilot
    with TestClient(p.app) as client:
        lease = admit(client, p)
        if operation in {"bind", "result", "failure"}:
            assert client.post(f"{p.task_root}/attempt", json={**lease, "comfy_prompt_id": None}).status_code == 200
        if operation in {"result", "failure"}:
            assert client.post(f"{p.task_root}/attempt", json={**lease, "comfy_prompt_id": "fake-prompt"}).status_code == 200
        if revoke == "key":
            p.db.execute("UPDATE production_worker_keys SET revoked_at=?", (datetime.now(UTC).isoformat(),))
        elif revoke == "approval":
            approval = p.paired[5]
            p.paired[1].revoke(approval.approval_id, request_digest=approval.approval_request_digest,
                               reason="runner fixture revoke")
        else:
            # Rotate to a syntactically valid, manually planted legacy lease.
            lease["lease_token"] = "planted-legacy-token-for-test"
            p.db.execute("UPDATE production_jobs SET lease_token_digest=? WHERE production_job_id=?",
                         (hashlib.sha256(lease["lease_token"].encode()).hexdigest(), p.job.production_job_id))
        original = facts(p)
        path, payload = {
            "heartbeat": (f"{p.root}/heartbeat", lease),
            "reserve": (f"{p.task_root}/attempt", {**lease, "comfy_prompt_id": None}),
            "bind": (f"{p.task_root}/attempt", {**lease, "comfy_prompt_id": "fake-prompt"}),
            "result": (f"{p.task_root}/result", result(p, lease)),
            "failure": (f"{p.task_root}/failure", {**lease, "comfy_prompt_id": "fake-prompt", "failure_code": "FIXTURE_FAILURE"}),
        }[operation]
        response = client.post(path, json=payload)
        assert response.status_code == 409, response.text
        assert facts(p) == original


def test_mutation_guards_and_actual_writes_share_immediate_transaction(pilot, monkeypatch):
    p = pilot
    guarded = p.service.repository._require_lease
    checks = []

    def require_locked(*args, **kwargs):
        assert p.db.connection.in_transaction, "lease check outside mutation transaction"
        checks.append(True)
        return guarded(*args, **kwargs)

    with TestClient(p.app) as client:
        lease = admit(client, p)
        monkeypatch.setattr(p.service.repository, "_require_lease", require_locked)
        assert client.post(f"{p.root}/heartbeat", json=lease).status_code == 200
        assert client.post(f"{p.task_root}/attempt", json={**lease, "comfy_prompt_id": None}).status_code == 200
        assert client.post(f"{p.task_root}/attempt", json={**lease, "comfy_prompt_id": "fake-prompt"}).status_code == 200
        assert client.post(f"{p.task_root}/failure", json={**lease, "comfy_prompt_id": "fake-prompt", "failure_code": "FIXTURE_FAILURE"}).status_code == 200
    assert len(checks) >= 4


def test_restart_with_unresolved_attempt_cannot_claim_or_allocate_new_attempt(pilot):
    p = pilot
    with TestClient(p.app) as client:
        lease = admit(client, p)
        assert client.post(f"{p.task_root}/attempt", json={**lease, "comfy_prompt_id": None}).status_code == 200
        p.db.execute("UPDATE production_jobs SET lease_expires_at=?", ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),))
        p.db.close()
        p.db.open()
        p.db.apply_migrations()
        original = facts(p)
        assert client.post(f"{p.root}/claim", json={"executor_id": lease["executor_id"]}).status_code == 409
        assert client.post(f"{p.task_root}/attempt", json={**lease, "comfy_prompt_id": None}).status_code == 409
        assert facts(p) == original
        assert p.db.scalar("SELECT COUNT(*) FROM production_attempts") == 1


def test_explicit_local_console_b_enrollment_pins_policy_and_default_stays_strict(paired, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    db, _, _, _, _, _, _, _, trust = paired
    # Only mock OS console interaction; persistence and cryptographic identities
    # remain real. No owner device or live enrollment is touched.
    monkeypatch.setattr(worker_pairing, "_require_local_console", lambda _: "RUNNER_FIXTURE_ONLY")
    monkeypatch.setattr("builtins.input", lambda prompt: prompt.split("[")[1].split("]")[0])
    for executor, policy in [("fixture-b", MODEL), ("fixture-strict", None)]:
        public = Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        options = {} if policy is None else {"trust_model": policy}
        key_id = trust.enroll_from_local_console(executor, public, **options)
        row = db.fetchone("SELECT * FROM production_worker_keys WHERE key_id=?", (key_id,))
        assert (row["trust_model"] == MODEL) is (policy is not None)
    db.apply_migrations()
    db.apply_migrations()
    assert db.scalar("SELECT MAX(version) FROM schema_migrations") == 24
