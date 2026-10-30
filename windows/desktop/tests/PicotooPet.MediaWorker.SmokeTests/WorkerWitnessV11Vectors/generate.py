"""Offline Core oracle, NOT a Windows signer, enrollment tool or Worker.

Run from the repository root with the existing Python test environment. The
public RFC 8032 test seed below must NEVER be used as a production credential.
No database, network, application settings or credential store is accessed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from picotoopet_core.production.versioned_plan import WorkerWitnessV11


def vectors() -> dict:
    # RFC 8032 section 7.1, TEST 1: intentionally public test-only material.
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
    ))
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    assert public.hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    fingerprint = hashlib.sha256(public).hexdigest()
    cases = []
    for suffix in ("", ".123456"):
        data = dict(
            worker_key_id="wk-" + fingerprint[:40],
            executor_id="windows-same-exe-worker",
            production_job_id='job-参考图-😀-"\\\n',
            plan_digest="1" * 64,
            issued_at=f"2026-10-29T12:00:00{suffix}+00:00",
            expires_at=f"2026-10-29T12:00:30{suffix}+00:00",
            nonce="2" * 64,
            worker_executable_sha256="3" * 64,
            journal_digest="4" * 64,
            journal_generation=9007199254740993,
            journal_state="NO_PRIOR_POST",
            references=[dict(
                production_task_id="task-01", shot_id="shot-01",
                asset_id="asset-01", approval_id="approval-01",
                approval_request_digest="5" * 64,
                source_sha256="6" * 64, source_bytes=123,
                source_relative_path="references/参考图.png",
                snapshot_sha256="6" * 64, snapshot_bytes=123,
                snapshot_receipt_sha256="7" * 64,
                graph_digest="8" * 64,
                snapshot_relative_path="snapshots/参考图.png",
            )],
            signature="a" * 128,
        )
        unsigned = WorkerWitnessV11.model_validate(data)
        payload = unsigned.signed_payload()
        data["signature"] = private.sign(payload).hex()
        witness = WorkerWitnessV11.model_validate(data)
        assert witness.signed_payload() == payload
        private.public_key().verify(bytes.fromhex(witness.signature), payload)
        # A correct primitive must reject even a single byte appended to payload.
        try:
            private.public_key().verify(bytes.fromhex(witness.signature), payload + b"\n")
        except InvalidSignature:
            pass
        else:
            raise AssertionError("tampered payload accepted")
        cases.append(dict(
            name="utc-fractional" if suffix else "utc-whole-second",
            witness=witness.model_dump(mode="json"),
            signed_payload_utf8_hex=payload.hex(),
            signed_payload_sha256=hashlib.sha256(payload).hexdigest(),
        ))
    return dict(
        purpose="OFFLINE TEST ONLY; no Windows signer or production identity",
        frozen_core_commit="22cda5f12487b0ecd09e87b248350e436760e51f",
        public_key_hex=public.hex(), public_key_sha256=fingerprint, cases=cases,
    )


if __name__ == "__main__":
    target = Path(__file__).with_name("vectors.json")
    encoded = json.dumps(vectors(), ensure_ascii=False, indent=2) + "\n"
    # Regeneration is explicit; review the diff rather than blessing new bytes.
    target.write_text(encoded, encoding="utf-8")
    print("CORE_OFFLINE_WITNESS_VECTORS=PASS; WINDOWS_SIGNER=UNVERIFIED; I2V=BLOCKED")
