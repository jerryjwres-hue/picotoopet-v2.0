"""Native Core HTTP/SQLite/Ed25519 LTX first-attempt admission; no GPU."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from picotoopet_core.api.errors import install_error_handlers
from picotoopet_core.api.routes import production
from picotoopet_core.production.ltx_admission import LtxWorkerWitnessV12, vendor_intent_digest
from picotoopet_core.production.ltx_plan import LTX_SCOPE, LtxPilotFreezeRequestV12, freeze_ltx_pilot_job, load_frozen_ltx_pilot_plan
from picotoopet_core.production.reference_registration import ReferenceBatchRequestV1
from picotoopet_core.security.auth import require_auth
from test_reference_registration_api import PACKAGE, candidate, payload, state, _v11_service


@pytest.fixture()
def pilot(state):
    # 01. Use the existing real Core test repository and a synthetic portrait
    #     Creative ZIP. No production source, private media, or key enrollment.
    db, registration, approval, store, _ = state
    row = db.fetchone("SELECT * FROM creative_packages WHERE creative_package_id=?", (PACKAGE,))
    manifest = json.loads(row["manifest_json"])
    store.resolve_managed_relative(row["package_relpath"]).unlink()
    stages = manifest["stage_results"]
    stages["creative_brief.v1"]["output_profile_id"] = "video.vertical.v1"
    stages["script.v1"]["target_duration_seconds"] = 12
    for beat in stages["script.v1"]["beats"]:
        beat["duration_seconds"] = 4
    for shot in stages["shot_plan.v1"]["shots"]:
        shot["duration_seconds"] = 4
    location, digest = store.write_creative_package(PACKAGE, manifest)
    db.execute(
        "UPDATE creative_packages SET package_digest=?,package_relpath=?,manifest_json=? "
        "WHERE creative_package_id=?", (digest, location, json.dumps(manifest), PACKAGE),
    )
    raw = payload(digest)
    raw["selected_references"] = [dict(candidate("shot-a"), rights_scope=LTX_SCOPE)]
    receipt = registration.register(
        ReferenceBatchRequestV1.model_validate(raw), idempotency_key="ltx-claim-batch",
    )
    approval.decide_for_control_center(
        approval_id=receipt.approval_id, decision="approve",
        request_digest=receipt.approval_request_digest, idempotency_key="ltx-claim-owner",
        resolved_by="synthetic-fixture", reason="fixture only",
    )
    service = _v11_service(state)
    job = freeze_ltx_pilot_job(service, LtxPilotFreezeRequestV12(
        creative_package_id=PACKAGE, approved_reference_id=receipt.approval_id,
        idempotency_key="ltx-claim-job",
    ))
    plan = load_frozen_ltx_pilot_plan(service, job.production_job_id)

    # 02. Real Ed25519 fixture key; the actual enrollment mechanism remains
    #     local-console-only. HTTP cannot set or change this trust model.
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    fingerprint = hashlib.sha256(public).hexdigest()
    key_id, executor = "wk-" + fingerprint[:40], "windows-same-exe-worker"
    db.execute(
        "INSERT INTO production_worker_keys(key_id,executor_id,public_key_hex,key_fingerprint,"
        "registered_by,operator_receipt_sha256,enrolled_at,trust_model) VALUES (?,?,?,?,?,?,?,?)",
        (key_id, executor, public.hex(), fingerprint, "TEST_FIXTURE_ONLY", "a"*64,
         datetime.now(UTC).isoformat(), "OPERATOR_TRUSTED_PRIVATE_HOST_V1"),
    )
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(production.router, prefix="/api/v1")
    app.state.services = SimpleNamespace(production=service)
    app.dependency_overrides[require_auth] = lambda: None
    return SimpleNamespace(db=db, service=service, registration=registration, receipt=receipt,
                           job=job, plan=plan, private=private, key=key_id, executor=executor,
                           root=f"/api/v1/production/jobs/{job.production_job_id}", app=app)


def issue(client, p):
    body = {"worker_key_id": p.key, "executor_id": p.executor, "plan_digest": p.plan.digest()}
    # 03. The legacy challenge route must not admit a held LTX plan.
    assert client.post(p.root + "/worker-challenge", json=body).status_code == 409
    response = client.post(p.root + "/ltx-worker-challenge", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["schema_version"] == "production.ltx.worker_challenge.v1"
    return response.json()


def witness(p, challenge, **changes):
    ref = p.plan.reference_asset
    now = datetime.now(UTC)
    draft = LtxWorkerWitnessV12.model_validate({
        "worker_key_id": p.key, "executor_id": p.executor,
        "production_job_id": p.job.production_job_id, "plan_digest": p.plan.digest(),
        "issued_at": now, "expires_at": now + timedelta(seconds=15), "nonce": challenge["nonce"],
        "worker_executable_sha256": "b"*64, "journal_digest": "c"*64,
        "journal_generation": 0, "journal_state": "NO_PRIOR_POST",
        "references": [{
            "production_task_id": p.plan.production_task_id, "shot_id": p.plan.shot_id,
            "asset_id": ref.asset_id, "approval_id": ref.approval_id,
            "approval_request_digest": ref.approval_request_digest,
            "source_sha256": ref.sha256, "source_bytes": ref.bytes,
            "source_relative_path": ref.input_relative_path,
            "snapshot_sha256": ref.sha256, "snapshot_bytes": ref.bytes,
            "snapshot_receipt_sha256": "d"*64, "graph_digest": vendor_intent_digest(p.plan),
            "snapshot_relative_path": "PicotooPet/snapshots/fixture.png",
        }], "signature": "1"*128,
    })
    draft = draft.model_copy(update=changes)
    return draft.model_copy(update={"signature": p.private.sign(draft.signed_payload()).hex()})


def facts(p):
    return [tuple(row) for row in p.db.fetchall("SELECT * FROM production_jobs")], [
        tuple(row) for row in p.db.fetchall("SELECT * FROM production_tasks")], [
        tuple(row) for row in p.db.fetchall("SELECT * FROM production_attempts")]


def test_ltx_signed_claim_reserves_one_attempt_and_no_legacy_lease(pilot):
    p = pilot
    with TestClient(p.app) as client:
        challenge = issue(client, p)
        proof = witness(p, challenge)
        # 04. Ordinary Bearer cannot allocate the renderer-specific attempt.
        assert client.post(p.root + "/claim", json={"executor_id": p.executor}).status_code == 409
        assert client.post(p.root + "/ltx-claim", json={"executor_id": p.executor}).status_code == 422
        assert not p.db.fetchall("SELECT * FROM production_attempts")
        # The same valid signed request racing in four threads consumes once.
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: client.post(
                p.root + "/ltx-claim", json=proof.model_dump(mode="json")), range(4)))
        assert sorted(r.status_code for r in responses) == [200, 409, 409, 409]
        body = next(r.json() for r in responses if r.status_code == 200)
        assert body["plan"] == p.plan.model_dump(mode="json")
        assert body["vendor_intent_digest"] == vendor_intent_digest(p.plan)
        assert body["production_task_id"] == p.plan.production_task_id
        row = p.db.fetchone("SELECT * FROM production_jobs")
        assert row["lease_token_digest"] == hashlib.sha256(body["lease_token"].encode()).hexdigest()
        assert row["production_profile"] == "production.ltx.desktop.local.v1"
        assert row["status"] == "Rendering"
        task = p.db.fetchone("SELECT * FROM production_tasks")
        attempt = p.db.fetchone("SELECT * FROM production_attempts")
        assert task["workflow_id"] == p.plan.workflow_id and task["attempt_count"] == 1
        assert attempt["production_attempt_id"] == body["production_attempt_id"]
        assert task["comfy_prompt_id"] is None and attempt["comfy_prompt_id"] is None
        assert p.db.scalar("SELECT COUNT(*) FROM production_worker_challenges WHERE consumed_at IS NOT NULL") == 1
        old = facts(p)
        assert client.post(p.root + "/claim", json={"executor_id": p.executor}).status_code == 409
        assert facts(p) == old
        # Expired reservation is not permission for another attempt.
        p.db.execute("UPDATE production_jobs SET lease_expires_at=?",
                     ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),))
        assert client.post(p.root + "/ltx-claim", json=proof.model_dump(mode="json")).status_code == 409
        assert p.db.scalar("SELECT COUNT(*) FROM production_attempts") == 1


@pytest.mark.parametrize("case", ["signature", "graph", "journal", "key", "approval", "expired"])
def test_bad_or_revoked_witness_cannot_consume_nonce_or_reserve(pilot, case):
    p = pilot
    with TestClient(p.app) as client:
        challenge = issue(client, p)
        proof = witness(p, challenge)
        if case == "signature":
            proof = proof.model_copy(update={"signature": "2"*128})
        elif case == "graph":
            ref = proof.references[0].model_copy(update={"graph_digest": "f"*64})
            proof = witness(p, challenge, references=(ref,))
        elif case == "journal":
            proof = witness(p, challenge, journal_state="UNCERTAIN")
        elif case == "key":
            p.db.execute("UPDATE production_worker_keys SET revoked_at=?",
                         (datetime.now(UTC).isoformat(),))
        elif case == "approval":
            p.registration.revoke(
                p.receipt.approval_id, request_digest=p.receipt.approval_request_digest,
                reason="fixture revoke",
            )
        else:
            now = datetime.now(UTC)
            proof = witness(p, challenge, issued_at=now-timedelta(seconds=20),
                            expires_at=now-timedelta(seconds=5))
        before = facts(p)
        response = client.post(p.root + "/ltx-claim", json=proof.model_dump(mode="json"))
        assert response.status_code == 409, response.text
        assert facts(p) == before
        assert p.db.scalar("SELECT COUNT(*) FROM production_worker_challenges WHERE consumed_at IS NOT NULL") == 0


def test_ltx_nonce_and_attempt_rollback_together(pilot):
    p = pilot
    with TestClient(p.app, raise_server_exceptions=False) as client:
        proof = witness(p, issue(client, p))
        before = facts(p)
        # 05. Force a real SQLite write failure AFTER signature verification.
        p.db.execute("CREATE TRIGGER fixture_abort_ltx_attempt BEFORE INSERT ON production_attempts "
                     "BEGIN SELECT RAISE(ABORT, 'fixture attempt write failure'); END")
        assert client.post(p.root + "/ltx-claim", json=proof.model_dump(mode="json")).status_code != 200
        assert facts(p) == before
        assert p.db.scalar("SELECT COUNT(*) FROM production_worker_challenges WHERE consumed_at IS NOT NULL") == 0
        p.db.execute("DROP TRIGGER fixture_abort_ltx_attempt")
        response = client.post(p.root + "/ltx-claim", json=proof.model_dump(mode="json"))
        assert response.status_code == 200, response.text


@pytest.mark.parametrize("mutation", ["token", "attempt", "intent", "key", "approval", "snapshot", "witness", "expiry"])
def test_ltx_current_lease_rechecks_before_vendor_post_and_renewal(pilot, mutation):
    p = pilot
    with TestClient(p.app) as client:
        proof = witness(p, issue(client, p))
        claim = client.post(p.root + "/ltx-claim", json=proof.model_dump(mode="json"))
        assert claim.status_code == 200, claim.text
        data = claim.json()
        lease = {key: data[key] for key in (
            "executor_id", "lease_token", "production_attempt_id",
            "plan_digest", "vendor_intent_digest",
        )}
        # 06. Rechecking and extending a lease never consumes a new nonce
        #     or increases the first-attempt budget.
        before = facts(p)
        checked = client.post(p.root + "/ltx-lease/recheck", json=lease)
        assert checked.status_code == 200, checked.text
        assert checked.json()["production_attempt_id"] == data["production_attempt_id"]
        assert facts(p) == before
        heartbeat = client.post(p.root + "/ltx-lease/heartbeat", json=lease)
        assert heartbeat.status_code == 200, heartbeat.text
        assert p.db.scalar("SELECT COUNT(*) FROM production_attempts") == 1
        assert client.post(p.root + "/heartbeat", json={
            "executor_id": lease["executor_id"], "lease_token": lease["lease_token"],
        }).status_code == 409
        if mutation == "token":
            lease["lease_token"] = "forged-legacy-token"
        elif mutation == "attempt":
            lease["production_attempt_id"] = str(uuid4())
        elif mutation == "intent":
            lease["vendor_intent_digest"] = "0"*64
        elif mutation == "key":
            p.db.execute("UPDATE production_worker_keys SET revoked_at=?",
                         (datetime.now(UTC).isoformat(),))
        elif mutation == "approval":
            p.registration.revoke(
                p.receipt.approval_id, request_digest=p.receipt.approval_request_digest,
                reason="fixture revoke after claim",
            )
        elif mutation == "snapshot":
            p.db.execute("UPDATE production_tasks SET task_plan_json='{}'")
        elif mutation == "witness":
            p.db.execute("UPDATE production_worker_challenges SET admitted_witness_json='{}'")
        else:
            p.db.execute("UPDATE production_jobs SET lease_expires_at=?",
                         ((datetime.now(UTC)-timedelta(seconds=1)).isoformat(),))
        before = facts(p)
        for route in ("/ltx-lease/recheck", "/ltx-lease/heartbeat"):
            assert client.post(p.root + route, json=lease).status_code == 409
        assert facts(p) == before
        assert p.db.scalar("SELECT COUNT(*) FROM production_attempts") == 1
