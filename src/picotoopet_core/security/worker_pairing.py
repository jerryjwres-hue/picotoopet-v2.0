"""Mac Core's paired Worker public-key and one-use nonce authority.

Enrolment/revocation are ONLY local interactive macOS console operations, not
HTTP/Bearer endpoints. A paired software key proves possession by that account,
NOT that an untrusted same-user process is the actual signed Windows EXE.
Nothing here authorizes I2V GPU production.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from picotoopet_core.db.database import Database

if TYPE_CHECKING:
    import sqlite3

    from picotoopet_core.production.versioned_plan import WorkerWitnessV11


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _key_fingerprint(public_key: bytes) -> str:
    return hashlib.sha256(public_key).hexdigest()


def _verify_ed25519(public_hex: str, signature_hex: str, message: bytes) -> None:
    """Audited primitive; absent cryptography is a closed gate, never a fallback."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as error:
        raise ValueError("PRODUCTION_V11_ED25519_RUNTIME_UNAVAILABLE") from error
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex)).verify(
            bytes.fromhex(signature_hex), message
        )
    except (ValueError, InvalidSignature) as error:
        raise ValueError("PRODUCTION_V11_WORKER_SIGNATURE_INVALID") from error


def _require_local_console(database_path: Path) -> str:
    """Check OS console ownership and interactive session, NEVER caller booleans.

    No remote network-facing enrollment. macOS console uid/TTY plus local DB file
    ownership is the minimum operator gate. Same-uid local malware remains out
    of scope; no claim of Secure Enclave, attested process identity or 2FA.
    """
    if (
        sys.platform != "darwin"
        or os.geteuid() == 0
        or not sys.stdin.isatty()
        or not sys.stdout.isatty()
    ):
        raise ValueError("PRODUCTION_V11_OPERATOR_CONSOLE_REQUIRED")
    try:
        console = os.stat("/dev/console")
        target = os.lstat(database_path)
        parent = os.lstat(database_path.parent)
    except OSError as error:
        raise ValueError("PRODUCTION_V11_OPERATOR_CONSOLE_REQUIRED") from error
    if (
        console.st_uid != os.geteuid()
        or target.st_uid != os.geteuid()
        or parent.st_uid != os.geteuid()
        or stat.S_ISLNK(target.st_mode)
        or not stat.S_ISREG(target.st_mode)
        or stat.S_ISLNK(parent.st_mode)
        or not stat.S_ISDIR(parent.st_mode)
        or bool(target.st_mode & 0o022)
        or bool(parent.st_mode & 0o022)
    ):
        raise ValueError("PRODUCTION_V11_OPERATOR_CONSOLE_REQUIRED")
    import pwd  # macOS-only; never imported by Windows HTTP/contract runtime

    return pwd.getpwuid(os.geteuid()).pw_name


class PairedWorkerTrust:
    MAX_ACTIVE_KEYS_PER_EXECUTOR = 2
    CHALLENGE_SECONDS = 30

    def __init__(self, database: Database) -> None:
        self.database = database

    def enroll_from_local_console(self, executor_id: str, public_key_hex: str) -> str:
        """Explicit operator-pinned key; never exposed via FastAPI."""
        import re

        operator = _require_local_console(self.database.path)
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", executor_id) is None:
            raise ValueError("PRODUCTION_V11_EXECUTOR_ID_INVALID")
        if re.fullmatch(r"[0-9a-f]{64}", public_key_hex) is None:
            raise ValueError("PRODUCTION_V11_WORKER_PUBLIC_KEY_INVALID")
        public_bytes = bytes.fromhex(public_key_hex)
        if public_bytes == bytes(32):
            raise ValueError("PRODUCTION_V11_WORKER_PUBLIC_KEY_INVALID")
        fingerprint = _key_fingerprint(public_bytes)
        key_id = "wk-" + fingerprint[:40]
        confirmation = f"ENROLL {executor_id} {fingerprint[:16]}"
        print(f"Windows Worker: {executor_id}\nEd25519 public-key SHA256: {fingerprint}")
        if input(f"Type exactly [{confirmation}] to enroll: ").strip() != confirmation:
            raise ValueError("PRODUCTION_V11_OPERATOR_CONFIRMATION_REQUIRED")
        now = _stamp(datetime.now(UTC))
        receipt = hashlib.sha256(
            json.dumps(
                [key_id, executor_id, fingerprint, operator, now, secrets.token_hex(16)],
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT key_id FROM production_worker_keys "
                "WHERE key_fingerprint=? OR key_id=?",
                (fingerprint, key_id),
            ).fetchone()
            if existing is not None:
                raise ValueError("PRODUCTION_V11_WORKER_KEY_ALREADY_REGISTERED")
            active = connection.execute(
                "SELECT COUNT(*) FROM production_worker_keys "
                "WHERE executor_id=? AND revoked_at IS NULL",
                (executor_id,),
            ).fetchone()[0]
            if active >= self.MAX_ACTIVE_KEYS_PER_EXECUTOR:
                raise ValueError("PRODUCTION_V11_WORKER_KEY_ROTATION_LIMIT")
            connection.execute(
                "INSERT INTO production_worker_keys("
                "key_id,executor_id,public_key_hex,key_fingerprint,registered_by,"
                "operator_receipt_sha256,enrolled_at) VALUES (?,?,?,?,?,?,?)",
                (key_id, executor_id, public_key_hex, fingerprint, operator, receipt, now),
            )
        return key_id

    def revoke_from_local_console(self, key_id: str) -> None:
        """Irreversible local action; old key ID may not be re-enabled."""
        operator = _require_local_console(self.database.path)
        row = self.database.fetchone(
            "SELECT executor_id,key_fingerprint,revoked_at FROM production_worker_keys "
            "WHERE key_id=?", (key_id,),
        )
        if row is None:
            raise ValueError("PRODUCTION_V11_WORKER_KEY_UNKNOWN")
        if row["revoked_at"] is not None:
            return
        confirmation = f"REVOKE {key_id}"
        print(f"Revoke {row['executor_id']} fingerprint {row['key_fingerprint']}")
        if input(f"Type exactly [{confirmation}] to revoke: ").strip() != confirmation:
            raise ValueError("PRODUCTION_V11_OPERATOR_CONFIRMATION_REQUIRED")
        with self.database.transaction() as connection:
            updated = connection.execute(
                "UPDATE production_worker_keys SET revoked_at=?,revoked_reason=? "
                "WHERE key_id=? AND revoked_at IS NULL",
                (_stamp(datetime.now(UTC)), f"local-console:{operator}", key_id),
            )
            if updated.rowcount != 1:
                raise ValueError("PRODUCTION_V11_WORKER_KEY_REVOKED")

    def issue_challenge(self, key_id: str, production_job_id: str, executor_id: str,
                        plan_digest: str) -> str:
        """Internal-only Core challenge API; no Bearer route is permitted."""
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=self.CHALLENGE_SECONDS)
        with self.database.transaction() as connection:
            key = connection.execute(
                "SELECT executor_id,revoked_at FROM production_worker_keys WHERE key_id=?",
                (key_id,),
            ).fetchone()
            if key is None or key["revoked_at"] is not None or key["executor_id"] != executor_id:
                raise ValueError("PRODUCTION_V11_WORKER_KEY_UNTRUSTED")
            job = connection.execute(
                "SELECT plan_digest,plan_json FROM production_jobs "
                "WHERE production_job_id=?", (production_job_id,),
            ).fetchone()
            if job is None or job["plan_digest"] != plan_digest:
                raise ValueError("PRODUCTION_V11_CHALLENGE_SCOPE_INVALID")
            try:
                raw_plan = json.loads(job["plan_json"])
            except (ValueError, TypeError) as error:
                raise ValueError("PRODUCTION_V11_CHALLENGE_SCOPE_INVALID") from error
            if raw_plan.get("schema_version") != "1.1":
                raise ValueError("PRODUCTION_V11_CHALLENGE_SCOPE_INVALID")
            canonical = json.dumps(raw_plan, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False).encode("utf-8")
            if hashlib.sha256(canonical).hexdigest() != plan_digest:
                raise ValueError("PRODUCTION_V11_CHALLENGE_SCOPE_INVALID")
            if connection.execute(
                "SELECT 1 FROM production_worker_challenges "
                "WHERE key_id=? AND production_job_id=? AND consumed_at IS NULL AND expires_at>?",
                (key_id, production_job_id, _stamp(now)),
            ).fetchone() is not None:
                raise ValueError("PRODUCTION_V11_CHALLENGE_ALREADY_ACTIVE")
            nonce = secrets.token_hex(32)
            connection.execute(
                "INSERT INTO production_worker_challenges("
                "nonce_digest,key_id,executor_id,production_job_id,plan_digest,"
                "issued_at,expires_at) VALUES (?,?,?,?,?,?,?)",
                (hashlib.sha256(nonce.encode()).hexdigest(), key_id, executor_id,
                 production_job_id, plan_digest, _stamp(now), _stamp(expires)),
            )
        return nonce

    def verify_locked(self, connection: sqlite3.Connection, witness: WorkerWitnessV11,
                      *, redeem: bool) -> None:
        """Check real pinned key/signature + Core nonce; caller owns BEGIN IMMEDIATE.

        Redeem=True writes one-use consumption in the SAME transaction as caller's
        future claim, never in a separate preflight. Current production claim
        paths still deny unconditionally, even if this verifier succeeds.
        """
        if not connection.in_transaction:
            raise ValueError("PRODUCTION_V11_WITNESS_TRANSACTION_REQUIRED")
        now = datetime.now(UTC)
        witness.require_fresh(now)
        key = connection.execute(
            "SELECT public_key_hex,executor_id,revoked_at FROM production_worker_keys "
            "WHERE key_id=?", (witness.worker_key_id,),
        ).fetchone()
        if key is None or key["revoked_at"] is not None or key["executor_id"] != witness.executor_id:
            raise ValueError("PRODUCTION_V11_WORKER_KEY_UNTRUSTED")
        _verify_ed25519(key["public_key_hex"], witness.signature, witness.signed_payload())
        digest = hashlib.sha256(witness.nonce.encode("ascii")).hexdigest()
        challenge = connection.execute(
            "SELECT * FROM production_worker_challenges WHERE nonce_digest=?", (digest,),
        ).fetchone()
        if (
            challenge is None
            or challenge["key_id"] != witness.worker_key_id
            or challenge["executor_id"] != witness.executor_id
            or challenge["production_job_id"] != witness.production_job_id
            or challenge["plan_digest"] != witness.plan_digest
            or challenge["consumed_at"] is not None
            or datetime.fromisoformat(challenge["issued_at"]) > witness.issued_at
            or datetime.fromisoformat(challenge["expires_at"]) <= now
            or witness.expires_at > datetime.fromisoformat(challenge["expires_at"])
        ):
            raise ValueError("PRODUCTION_V11_WITNESS_CHALLENGE_INVALID")
        if redeem:
            updated = connection.execute(
                "UPDATE production_worker_challenges SET consumed_at=? "
                "WHERE nonce_digest=? AND consumed_at IS NULL AND expires_at>?",
                (_stamp(now), digest, _stamp(now)),
            )
            if updated.rowcount != 1:
                raise ValueError("PRODUCTION_V11_WITNESS_REPLAY")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local macOS console only; never a LAN Worker key registration API"
    )
    parser.add_argument("--database", required=True, type=Path)
    sub = parser.add_subparsers(dest="action", required=True)
    enroll = sub.add_parser("enroll")
    enroll.add_argument("--executor-id", required=True)
    enroll.add_argument("--public-key-hex", required=True)
    revoke = sub.add_parser("revoke")
    revoke.add_argument("--key-id", required=True)
    args = parser.parse_args()
    # ── Before even opening the SQLite file, reject non-console privilege. ──
    _require_local_console(args.database)
    db = Database(args.database)
    db.open()
    try:
        db.apply_migrations()
        trust = PairedWorkerTrust(db)
        if args.action == "enroll":
            print(trust.enroll_from_local_console(args.executor_id, args.public_key_hex))
        else:
            trust.revoke_from_local_console(args.key_id)
            print("Worker key revoked.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
