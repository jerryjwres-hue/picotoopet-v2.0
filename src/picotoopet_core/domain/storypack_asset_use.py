"""Exact-content Owner asset-use attestation on the existing audit ledger.

An owner's assertion is NOT independent legal verification and cannot replace
MASTER provenance review, a production admission decision, or GPU authorization.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.audit.writer import AuditWriter, canonical_hash
from picotoopet_core.db.database import Database
from picotoopet_core.domain.storypack import StoryPackV1
from picotoopet_core.domain.storypack_owner_commit import StoryboardReviewService
from picotoopet_core.security.owner_principal import OwnerPrincipal

_ACTION_COMMIT = "studio.storypack.asset_use.attest"
_ACTION_REVOKE = "studio.storypack.asset_use.revoke"
_RESOURCE_TYPE = "storypack.asset_use_attestation"
_IDEMPOTENCY_TYPE = "storypack.asset_use_attestation"
_SHA_PATTERN = r"^[0-9a-f]{64}$"
_ASSET_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,99}$"


class AssetUseClaim(BaseModel):
    """One affirmative, exact-byte claim for a declared StoryPack asset."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    ref: str = Field(pattern=_ASSET_PATTERN)
    asset_sha256: str = Field(pattern=_SHA_PATTERN)
    basis: Literal["self_created", "commercial_license", "written_permission"]
    evidence_sha256: str | None = Field(default=None, pattern=_SHA_PATTERN)
    commercial_ai_generation: Literal[True]
    commercial_distribution: Literal[True]


class AssetUseError(ValueError):
    """Stable fail-closed error without leaking StoryPack or private evidence."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _sha(payload: dict) -> str:
    # Canonical JSON 的同一版本在重试和撤销核验中产生稳定哈希。
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _owner_ref(principal: OwnerPrincipal) -> str:
    # 日志只保存 Owner 凭据 ID 的不可逆摘要，从不保存实际 Bearer。
    return hashlib.sha256(principal.credential_id.encode("utf-8")).hexdigest()


def _verified_event(connection, review_id: str):
    """Recalculate the existing immutable audit event's hash."""
    row = connection.execute(
        "SELECT * FROM audit_events WHERE audit_id=? AND action=?",
        (review_id, _ACTION_COMMIT),
    ).fetchone()
    if row is None:
        raise AssetUseError("ASSET_USE_ATTESTATION_NOT_FOUND")
    try:
        details = json.loads(row["details_redacted_json"])
        expected = {
            "audit_id": row["audit_id"],
            "trace_id": row["trace_id"],
            "actor_type": row["actor_type"],
            "actor_id": row["actor_id"],
            "action": row["action"],
            "resource_type": row["resource_type"],
            "resource_id": row["resource_id"],
            "decision": row["decision"],
            "reason_code": row["reason_code"],
            "details_redacted_json": row["details_redacted_json"],
            "previous_hash": row["previous_hash"],
            "created_at": row["created_at"],
        }
        if (
            not isinstance(details, dict)
            or row["resource_type"] != _RESOURCE_TYPE
            or row["decision"] != "OWNER_ATTESTATION_ONLY"
            or not hmac.compare_digest(canonical_hash(expected), row["event_hash"])
        ):
            raise ValueError("bad attestation ledger evidence")
    except (ValueError, KeyError, TypeError) as error:
        raise AssetUseError("ASSET_USE_AUDIT_INVALID") from error
    return row, details


class AssetUseAttestationService:
    """Attest commercial animation use of SHA-bound assets, without tasks."""

    def __init__(self, database: Database, objects_dir: Path) -> None:
        self.database = database
        self.storyboard = StoryboardReviewService(database, objects_dir)
        self.audit = AuditWriter(database)

    def prepare(self, pack: StoryPackV1, claims: list[AssetUseClaim]) -> dict:
        # Always refresh the real managed object bytes, never accept client hashes alone.
        advisory = self.storyboard.subject(pack)
        subject = advisory["review"]
        if subject["subject_sha256"] is None:
            raise AssetUseError("ASSET_USE_MANAGED_BYTES_UNVERIFIED")
        required = {
            asset["ref"]: asset["sha256"]
            for asset in subject["subject"]["assets"]
        }
        submitted = {claim.ref: claim for claim in claims}
        if (
            len(submitted) != len(claims)
            or len(submitted) != len(required)
            or set(submitted) != set(required)
            or any(
                claim.asset_sha256 != required[claim.ref]
                for claim in claims
            )
        ):
            raise AssetUseError("ASSET_USE_ASSET_SET_OR_SHA_MISMATCH")
        for claim in claims:
            # A licence/permission must at least refer to a fixed evidence digest.
            if claim.basis != "self_created" and claim.evidence_sha256 is None:
                raise AssetUseError("ASSET_USE_EXTERNAL_EVIDENCE_DIGEST_REQUIRED")
            if claim.basis == "self_created" and claim.evidence_sha256 is not None:
                raise AssetUseError("ASSET_USE_SELF_CREATED_EVIDENCE_UNEXPECTED")

        # Claim order never changes authorization meaning; bind the full sorted set.
        normalized = [
            claim.model_dump(mode="json")
            for claim in sorted(claims, key=lambda item: item.ref)
        ]
        attestation_sha = _sha({
            "contract": "picotoo.owner-asset-use-subject.v1",
            "storypack_sha256": advisory["storypack_sha256"],
            "storyboard_subject_sha256": subject["subject_sha256"],
            "claims": normalized,
        })
        return {
            "status": "OWNER_ASSET_USE_READY_FOR_ATTESTATION",
            "storypack_sha256": advisory["storypack_sha256"],
            "storyboard_subject_sha256": subject["subject_sha256"],
            "attestation_sha256": attestation_sha,
            "claims": normalized,
            "rights_attested": False,
            "rights_independently_verified": False,
            "master_rights_approved": False,
            "gpu_authorized": False,
            "can_queue": False,
        }

    @staticmethod
    def _receipt(review_id: str, prepared: dict, status: str) -> dict:
        return {
            "attestation_id": review_id,
            "status": status,
            "storypack_sha256": prepared["storypack_sha256"],
            "storyboard_subject_sha256": prepared["storyboard_subject_sha256"],
            "attestation_sha256": prepared["attestation_sha256"],
            "rights_attested": True,
            # An Owner assertion never proves independent licence/provenance.
            "rights_independently_verified": False,
            "master_rights_approved": False,
            "gpu_authorized": False,
            "can_queue": False,
        }

    @staticmethod
    def _verify_event(connection, row, details: dict, prepared: dict,
                      principal: OwnerPrincipal, subject_key: str) -> None:
        expected = prepared["attestation_sha256"]
        if not (
            row["resource_id"] == expected
            and row["actor_id"] == principal.actor_id
            and details.get("subject_key") == subject_key
            and details.get("storypack_sha256") == prepared["storypack_sha256"]
            and details.get("storyboard_subject_sha256") == prepared["storyboard_subject_sha256"]
            and details.get("attestation_sha256") == expected
            and details.get("grant_ref") == _owner_ref(principal)
            and details.get("registry_revision") == principal.registry_revision
        ):
            raise AssetUseError("ASSET_USE_ATTESTATION_STALE")
        try:
            expiry = datetime.fromisoformat(details["expires_at"])
            if expiry.tzinfo is None or datetime.now(UTC) >= expiry:
                raise AssetUseError("ASSET_USE_ATTESTATION_EXPIRED")
        except (ValueError, TypeError, KeyError) as error:
            raise AssetUseError("ASSET_USE_ATTESTATION_EXPIRED") from error
        if connection.execute(
            "SELECT 1 FROM audit_events WHERE action=? AND resource_id=? LIMIT 1",
            (_ACTION_REVOKE, row["audit_id"]),
        ).fetchone():
            raise AssetUseError("ASSET_USE_ATTESTATION_REVOKED")

    def commit(self, *, pack: StoryPackV1, claims: list[AssetUseClaim],
               subject_key: str, principal: OwnerPrincipal,
               expected_attestation_sha256: str, idempotency_key: str,
               expires_seconds: int) -> dict:
        if not 10 <= len(idempotency_key) <= 200:
            raise AssetUseError("ASSET_USE_IDEMPOTENCY_KEY_INVALID")
        key_ref = "asset-use:" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        with self.database.transaction() as connection:
            prepared = self.prepare(pack, claims)
            current = prepared["attestation_sha256"]
            if not hmac.compare_digest(current, expected_attestation_sha256):
                raise AssetUseError("ASSET_USE_SUBJECT_CHANGED")
            request_sha = _sha({
                "subject_key": subject_key,
                "attestation_sha256": current,
                "actor_id": principal.actor_id,
                "grant_ref": _owner_ref(principal),
                "registry_revision": principal.registry_revision,
                "expires_seconds": expires_seconds,
            })
            old = connection.execute(
                "SELECT resource_id FROM idempotency_keys "
                "WHERE idempotency_key=? AND resource_type=?",
                (key_ref, _IDEMPOTENCY_TYPE),
            ).fetchone()
            if old is not None:
                row, details = _verified_event(connection, old["resource_id"])
                if details.get("request_sha256") != request_sha:
                    raise AssetUseError("ASSET_USE_IDEMPOTENCY_CONFLICT")
                self._verify_event(
                    connection, row, details, prepared, principal, subject_key
                )
                return self._receipt(row["audit_id"], prepared, "OWNER_ASSET_USE_ALREADY_ATTESTED")

            attestation_id = self.audit.append(
                trace_id=current,
                actor_type="owner_principal",
                actor_id=principal.actor_id,
                action=_ACTION_COMMIT,
                resource_type=_RESOURCE_TYPE,
                resource_id=current,
                decision="OWNER_ATTESTATION_ONLY",
                reason_code=None,
                details={
                    "subject_key": subject_key,
                    "storypack_sha256": prepared["storypack_sha256"],
                    "storyboard_subject_sha256": prepared["storyboard_subject_sha256"],
                    "attestation_sha256": current,
                    "claims": prepared["claims"],
                    "grant_ref": _owner_ref(principal),
                    "registry_revision": principal.registry_revision,
                    "expires_at": (
                        datetime.now(UTC) + timedelta(seconds=expires_seconds)
                    ).isoformat(),
                    "request_sha256": request_sha,
                },
                connection=connection,
            )
            connection.execute(
                "INSERT INTO idempotency_keys "
                "(idempotency_key, resource_type, resource_id, created_at) "
                "VALUES (?, ?, ?, ?)",
                (key_ref, _IDEMPOTENCY_TYPE, attestation_id, datetime.now(UTC).isoformat()),
            )
        return self._receipt(attestation_id, prepared, "OWNER_ASSET_USE_ATTESTED")

    def verify(self, *, pack: StoryPackV1, claims: list[AssetUseClaim],
               subject_key: str, principal: OwnerPrincipal,
               attestation_id: str) -> dict:
        prepared = self.prepare(pack, claims)
        with self.database.transaction() as connection:
            row, details = _verified_event(connection, attestation_id)
            self._verify_event(connection, row, details, prepared, principal, subject_key)
        return self._receipt(attestation_id, prepared, "OWNER_ASSET_USE_CURRENT")

    def revoke(self, *, subject_key: str, attestation_id: str,
               principal: OwnerPrincipal) -> dict:
        with self.database.transaction() as connection:
            row, details = _verified_event(connection, attestation_id)
            if (
                details.get("subject_key") != subject_key
                or row["actor_id"] != principal.actor_id
                or details.get("grant_ref") != _owner_ref(principal)
                or details.get("registry_revision") != principal.registry_revision
            ):
                raise AssetUseError("ASSET_USE_REVOKE_SCOPE_MISMATCH")
            if connection.execute(
                "SELECT 1 FROM audit_events WHERE action=? AND resource_id=? LIMIT 1",
                (_ACTION_REVOKE, attestation_id),
            ).fetchone() is None:
                self.audit.append(
                    trace_id=attestation_id,
                    actor_type="owner_principal", actor_id=principal.actor_id,
                    action=_ACTION_REVOKE, resource_type=_RESOURCE_TYPE,
                    resource_id=attestation_id, decision="REVOKED",
                    reason_code="OWNER_REVOKED",
                    details={"subject_key": subject_key},
                    connection=connection,
                )
        return {
            "attestation_id": attestation_id,
            "status": "REVOKED",
            "can_queue": False,
        }
