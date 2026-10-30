"""Issue #165: real HTTP challenge transport + durable SQLite negative gates.

The key is inserted by a synthetic test fixture, NOT by an operator on a user
device. A challenge only permits a *signed proposal*, not an I2V GPU lease.
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
from test_reference_registration_api import state as reference_state
from test_v11_paired_worker_nonce import paired
from test_v11_worker_witness import _witness


@pytest.fixture()
def transport(paired):
    db, registration, service, job, plan, approval, private, key_id, trust = paired
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(production.router, prefix="/api/v1")
    app.state.services = SimpleNamespace(
        production=service, settings=SimpleNamespace(api_token="lan-transport-test-only")
    )
    url = f"/api/v1/production/jobs/{job.production_job_id}"
    payload = {
        "worker_key_id": key_id,
        "executor_id": "windows-same-exe-worker",
        "plan_digest": job.plan_digest,
    }
    return {
        "db": db, "registration": registration, "service": service, "job": job,
        "plan": plan, "approval": approval, "private": private, "key_id": key_id,
        "trust": trust, "app": app, "url": url, "payload": payload,
        "auth": {"Authorization": "Bearer lan-transport-test-only"},
        "paired": paired,
    }


def _request(case, client, body=None, *, url=None, auth=None):
    return client.post(
        url or f"{case['url']}/worker-challenge",
        json=case["payload"] if body is None else body,
        headers=case["auth"] if auth is None else auth,
    )


def _unchanged(case, expected_challenges=0, expected_attempts=0):
    db, job = case["db"], case["job"]
    assert db.scalar("SELECT COUNT(*) FROM production_worker_challenges") == expected_challenges
    assert db.scalar(
        "SELECT COUNT(*) FROM production_attempts WHERE production_job_id=?",
        (job.production_job_id,),
    ) == expected_attempts
    row = db.fetchone(
        "SELECT lease_token_digest,lease_executor_id,status FROM production_jobs "
        "WHERE production_job_id=?", (job.production_job_id,),
    )
    assert row["lease_token_digest"] is None
    assert row["lease_executor_id"] is None
    assert row["status"] == job.status.value


def test_real_http_bearer_only_transports_scoped_one_use_challenge(transport):
    case = transport
    with TestClient(case["app"]) as client:
        assert _request(case, client, auth={}).status_code == 401
        assert _request(case, client, auth={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get(f"{case['url']}/worker-challenge", headers=case["auth"]).status_code == 405
        assert _request(case, client).status_code == 200
    _unchanged(case, 1)


def test_challenge_response_exact_schema_no_store_and_hash_only_in_db(transport):
    case = transport
    with TestClient(case["app"]) as client:
        res = _request(case, client)
        assert res.status_code == 200, res.text
        data = res.json()
        assert set(data) == {
            "schema_version", "worker_key_id", "executor_id", "production_job_id",
            "plan_digest", "nonce", "issued_at", "expires_at",
        }
        assert data["schema_version"] == "production.worker_challenge.v1"
        assert data["worker_key_id"] == case["key_id"]
        assert data["executor_id"] == case["payload"]["executor_id"]
        assert data["production_job_id"] == case["job"].production_job_id
        assert data["plan_digest"] == case["job"].plan_digest
        assert len(data["nonce"]) == 64
        assert res.headers["cache-control"] == "no-store, private"
        assert res.headers["pragma"] == "no-cache"
        t0 = datetime.fromisoformat(data["issued_at"])
        t1 = datetime.fromisoformat(data["expires_at"])
        assert t0.tzinfo is not None and t1 - t0 == timedelta(seconds=30)
        row = case["db"].fetchone("SELECT * FROM production_worker_challenges")
        assert row["nonce_digest"] == hashlib.sha256(data["nonce"].encode()).hexdigest()
        assert row["nonce_digest"] != data["nonce"]
        assert row["consumed_at"] is None
        assert row["key_id"] == case["key_id"]
        assert row["plan_digest"] == case["job"].plan_digest
        # A successful challenge is NOT a Claim. Duplicate active requests
        # must not reveal or regenerate the same private random nonce.
        retry = _request(case, client)
        assert retry.status_code == 409
        assert retry.json()["error"]["code"] == "PRODUCTION_V11_CHALLENGE_UNAVAILABLE"
        assert data["nonce"] not in retry.text
        _unchanged(case, 1)


@pytest.mark.parametrize("changes", [
    {"worker_key_id": "unknown-worker-public-key"},
    {"executor_id": "wrong-executor"},
    {"plan_digest": "0" * 64},
])
def test_key_executor_plan_errors_are_all_generic_and_write_nothing(transport, changes):
    case = transport
    with TestClient(case["app"]) as client:
        res = _request(case, client, {**case["payload"], **changes})
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "PRODUCTION_V11_CHALLENGE_UNAVAILABLE"
    _unchanged(case)


def test_wrong_job_and_unprovisioned_or_revoked_key_generic(transport):
    case = transport
    with TestClient(case["app"]) as client:
        bad = _request(case, client, url="/api/v1/production/jobs/nonexistent/worker-challenge")
        assert bad.status_code == 409
        assert bad.json()["error"]["code"] == "PRODUCTION_V11_CHALLENGE_UNAVAILABLE"
        case["db"].execute(
            "UPDATE production_worker_keys SET revoked_at=? WHERE key_id=?",
            (datetime.now(UTC).isoformat(), case["key_id"]),
        )
        revoked = _request(case, client)
        assert revoked.status_code == 409
        assert revoked.json()["error"]["code"] == "PRODUCTION_V11_CHALLENGE_UNAVAILABLE"
    _unchanged(case)


def test_bearer_cannot_enroll_revoke_spend_nonce_or_force_gpu_claim(transport):
    case = transport
    with TestClient(case["app"]) as client:
        for suffix in (
            "/api/v1/production/worker-keys/register",
            "/api/v1/production/worker-keys/revoke",
            f"{case['url']}/worker-challenge/redeem",
        ):
            assert client.post(suffix, json=case["payload"], headers=case["auth"]).status_code == 404
        forged = _request(case, client, {**case["payload"], "verified": True})
        assert forged.status_code == 422
        claim = client.post(
            f"{case['url']}/claim",
            json={"executor_id": case["payload"]["executor_id"]},
            headers=case["auth"],
        )
        assert claim.status_code == 409
        assert claim.json()["error"]["code"] == "PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"
    _unchanged(case)


def test_missing_expired_or_revoked_approval_denies_before_nonce_write(transport):
    case = transport
    registration, approval, db = case["registration"], case["approval"], case["db"]
    registration.revoke(
        approval.approval_id,
        request_digest=approval.approval_request_digest,
        reason="fixture consent revoked",
    )
    with TestClient(case["app"]) as client:
        res = _request(case, client)
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "PRODUCTION_V11_CHALLENGE_UNAVAILABLE"
        db.execute(
            "UPDATE approvals SET status='Approved',expires_at=? WHERE approval_id=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), approval.approval_id),
        )
        assert _request(case, client).status_code == 409
        db.execute(
            "UPDATE approvals SET status='Rejected' WHERE approval_id=?",
            (approval.approval_id,),
        )
        assert _request(case, client).status_code == 409
    _unchanged(case)


def test_conflicting_lease_denied_without_nonce_or_attempt(transport):
    case, db, job = transport, transport["db"], transport["job"]
    db.execute(
        "UPDATE production_jobs SET lease_executor_id=?,lease_token_digest=?,lease_expires_at=? "
        "WHERE production_job_id=?",
        ("other-worker", "a" * 64, (datetime.now(UTC)+timedelta(minutes=2)).isoformat(),
         job.production_job_id),
    )
    with TestClient(case["app"]) as client:
        assert _request(case, client).status_code == 409
    assert db.scalar("SELECT COUNT(*) FROM production_worker_challenges") == 0
    assert db.scalar("SELECT COUNT(*) FROM production_attempts") == 0


@pytest.mark.parametrize("bound", [False, True])
def test_known_old_comfy_post_or_unbound_attempt_denied(transport, bound):
    case, db, job = transport, transport["db"], transport["job"]
    task = case["plan"].tasks[0]
    prompt = "old-comfy-prompt" if bound else None
    db.execute(
        "INSERT INTO production_attempts("
        "production_attempt_id,production_job_id,production_task_id,attempt_number,"
        "executor_id,comfy_prompt_id,status,started_at) VALUES (?,?,?,?,?,?,?,?)",
        ("old-attempt", job.production_job_id, task.production_task_id, 1,
         "windows-same-exe-worker", prompt, "Running", datetime.now(UTC).isoformat()),
    )
    db.execute(
        "UPDATE production_tasks SET status='Running',attempt_count=1,comfy_prompt_id=? "
        "WHERE production_task_id=?", (prompt, task.production_task_id),
    )
    with TestClient(case["app"]) as client:
        res = _request(case, client)
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "PRODUCTION_V11_CHALLENGE_UNAVAILABLE"
    assert db.scalar("SELECT COUNT(*) FROM production_worker_challenges") == 0
    assert db.scalar(
        "SELECT COUNT(*) FROM production_attempts WHERE production_job_id=?",
        (job.production_job_id,),
    ) == 1


def test_nonce_restart_expiry_cannot_replay_original_value(transport):
    case = transport
    with TestClient(case["app"]) as client:
        response = _request(case, client)
        assert response.status_code == 200
        nonce = response.json()["nonce"]
    db = case["db"]
    db.close()
    db.open()
    db.apply_migrations()
    with TestClient(case["app"]) as client:
        assert _request(case, client).status_code == 409
    # Simulate a genuinely expired record without bypassing the DB invariant.
    db.execute(
        "UPDATE production_worker_challenges SET issued_at=?,expires_at=? "
        "WHERE nonce_digest=?",
        (
            (datetime.now(UTC)-timedelta(seconds=45)).isoformat(),
            (datetime.now(UTC)-timedelta(seconds=15)).isoformat(),
            hashlib.sha256(nonce.encode()).hexdigest(),
        ),
    )
    with TestClient(case["app"]) as client:
        fresh = _request(case, client)
        assert fresh.status_code == 200
        assert fresh.json()["nonce"] != nonce
        assert db.scalar("SELECT COUNT(*) FROM production_worker_challenges") == 2
        assert db.scalar("SELECT COUNT(*) FROM production_worker_challenges WHERE consumed_at IS NOT NULL") == 0
    _unchanged(case, 2)


def test_nonce_collision_does_not_overwrite_old_record(transport, monkeypatch):
    case = transport
    with TestClient(case["app"]) as client:
        first = _request(case, client)
        assert first.status_code == 200
        original = first.json()["nonce"]
        db = case["db"]
        db.execute(
            "UPDATE production_worker_challenges SET issued_at=?,expires_at=?",
            (
                (datetime.now(UTC)-timedelta(seconds=60)).isoformat(),
                (datetime.now(UTC)-timedelta(seconds=30)).isoformat(),
            ),
        )
        monkeypatch.setattr("picotoopet_core.security.worker_pairing.secrets.token_hex",
                            lambda count: original)
        collision = _request(case, client)
        assert collision.status_code == 409
        assert collision.json()["error"]["code"] == "PRODUCTION_V11_CHALLENGE_UNAVAILABLE"
    _unchanged(case, 1)


def test_concurrent_same_job_requests_exactly_one_challenge(transport):
    case = transport
    with TestClient(case["app"]) as client:
        def post_once(_):
            return _request(case, client).status_code

        with ThreadPoolExecutor(max_workers=5) as pool:
            statuses = list(pool.map(post_once, range(5)))
    assert sorted(statuses) == [200, 409, 409, 409, 409]
    _unchanged(case, 1)


def test_valid_signature_and_challenge_still_get_409_and_never_spend_nonce(transport):
    case = transport
    with TestClient(case["app"]) as client:
        response = _request(case, client)
        assert response.status_code == 200
        data = response.json()
        issue = datetime.fromisoformat(data["issued_at"])
        witness_input = _witness(
            case["paired"][:6],
            worker_key_id=data["worker_key_id"],
            nonce=data["nonce"],
            issued_at=(issue+timedelta(milliseconds=10)).isoformat(),
            expires_at=(issue+timedelta(seconds=10)).isoformat(),
        )
        unsigned = WorkerWitnessV11.model_validate(witness_input)
        witness_input["signature"] = case["private"].sign(unsigned.signed_payload()).hex()
        preflight = client.post(
            f"{case['url']}/witness/preflight",
            json=witness_input, headers=case["auth"],
        )
        assert preflight.status_code == 409
        assert preflight.json()["error"]["code"] == "PRODUCTION_V11_WINDOWS_ATTESTATION_UNVERIFIED"
        result = client.post(
            f"{case['url']}/claim",
            json={"executor_id": case["payload"]["executor_id"]},
            headers=case["auth"],
        )
        assert result.status_code == 409
        assert result.json()["error"]["code"] == "PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"
    _unchanged(case, 1)
