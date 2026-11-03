"""#152 focused native TCP evidence, not TestClient or execution attestation.

All keys/approvals are existing disposable fixtures. Never run against a user
Core; no production gate, signer, schema or shipping consumer is modified.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
import uvicorn

from picotoopet_core.production.versioned_plan import WorkerWitnessV11
from test_v11_paired_worker_nonce import paired, reference_state  # noqa: F401
from test_v11_worker_challenge_transport import transport  # noqa: F401
from test_v11_worker_witness import _witness


@pytest.fixture()
def tcp(transport):
    case = transport
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(case["app"], log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 8
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline, "real TCP server unavailable"
            time.sleep(0.01)
        base = f"http://127.0.0.1:{listener.getsockname()[1]}"
        yield case, base
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive(), "test TCP server did not stop"


def post(case, base, suffix, data):
    request = urllib.request.Request(base + case["url"] + suffix,
        data=json.dumps(data).encode(), headers={**case["auth"], "Content-Type": "application/json"},
        method="POST")
    # Never use an ambient proxy for a CI loopback request.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=8) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def signed_wire(case, base):
    status, challenge = post(case, base, "/worker-challenge", case["payload"])
    assert status == 200
    data = _witness(case["paired"][:6], worker_key_id=case["key_id"],
        nonce=challenge["nonce"], issued_at=challenge["issued_at"],
        expires_at=challenge["expires_at"])
    unsigned = WorkerWitnessV11.model_validate(data)
    data["signature"] = case["private"].sign(unsigned.signed_payload()).hex()
    return data


def no_execution(case):
    db = case["db"]
    assert db.scalar("SELECT COUNT(*) FROM production_attempts") == 0
    assert db.scalar("SELECT COUNT(*) FROM production_packages") == 0
    job = db.fetchone("SELECT * FROM production_jobs WHERE production_job_id=?",
                     (case["job"].production_job_id,))
    assert job["lease_token_digest"] is None
    assert job["lease_executor_id"] is None
    assert job["lease_expires_at"] is None
    assert db.scalar("SELECT COUNT(*) FROM production_tasks WHERE attempt_count<>0 OR comfy_prompt_id IS NOT NULL") == 0


@pytest.mark.parametrize("attack,code", [
    ("signature", "PRODUCTION_V11_WORKER_SIGNATURE_INVALID"),
    ("replay", "PRODUCTION_V11_WINDOWS_ATTESTATION_UNVERIFIED"),
    ("uncertain-journal", "PRODUCTION_V11_WITNESS_POST_UNCERTAIN"),
    ("recovery-without-core-history", "PRODUCTION_V11_WITNESS_JOURNAL_MISMATCH"),
    ("approval-revoked", "REFERENCE_ASSET_APPROVAL_NOT_VERIFIED"),
    ("real-clock-expired", "PRODUCTION_V11_WITNESS_STALE"),
])
def test_actual_tcp_rejects_untrusted_admission(tcp, attack, code):
    case, base = tcp
    data = signed_wire(case, base)
    if attack == "signature":
        signature = bytes.fromhex(data["signature"])
        data["signature"] = (bytes([signature[0] ^ 1]) + signature[1:]).hex()
    elif attack == "uncertain-journal":
        data["journal_state"] = "UNCERTAIN"
    elif attack == "recovery-without-core-history":
        data["journal_state"] = "BOUND_RECOVERY"
    elif attack == "approval-revoked":
        case["registration"].revoke(case["approval"].approval_id,
            request_digest=case["approval"].approval_request_digest, reason="disposable TCP revocation")
    elif attack == "real-clock-expired":
        # Real Core 30s nonce/witness expiry, no clock patch or SQLite timestamp edit.
        delay = (datetime.fromisoformat(data["expires_at"]) - datetime.now(UTC)).total_seconds()
        assert 0 < delay <= 30
        time.sleep(delay + 0.1)

    count = 3 if attack == "replay" else 1
    with socket.socket() as sentinel:
        sentinel.bind(("127.0.0.1", 8188))
        sentinel.listen()
        sentinel.setblocking(False)
        with ThreadPoolExecutor(max_workers=count) as pool:
            replies = list(pool.map(lambda _: post(case, base, "/witness/preflight", data), range(count)))
        assert all(status == 409 and body["error"]["code"] == code for status, body in replies)
        status, body = post(case, base, "/claim", {"executor_id": case["payload"]["executor_id"]})
        assert status == 409 and body["error"]["code"] == "PRODUCTION_V11_WORKER_ADAPTER_REQUIRED"
        try:
            connection, _ = sentinel.accept()
        except BlockingIOError:
            pass
        else:
            connection.close()
            pytest.fail("Core denial contacted Comfy")
    no_execution(case)
    assert case["db"].scalar("SELECT COUNT(*) FROM production_worker_challenges") == 1
    assert case["db"].scalar("SELECT COUNT(*) FROM production_worker_challenges WHERE consumed_at IS NOT NULL") == 0
    print(f"NATIVE_TCP_{attack}=409; LEASE=0; ATTEMPT=0; COMFY_CONNECTION=0; NONCE=UNSPENT")
