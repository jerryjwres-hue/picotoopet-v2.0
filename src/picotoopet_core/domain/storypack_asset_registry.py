"""P0-1 existing-asset intake over the canonical ``artifacts`` and ``approvals`` tables.

NOT a second asset registry and NOT a second approval system:

* asset kinds map onto the existing ``storypack_<role>`` artifact types;
* Owner approval is an ordinary task-less ``approvals`` row decided in the existing
  Control Center (``/approvals/{id}/decision``);
* no table, column or schema version is added.

Two byte provenances are kept apart and never conflated:

* ``CORE_HASHED_MANAGED_COPY`` - Core received a copy through ``/studio/assets/import``
  and hashed the bytes in its own content-addressed store;
* ``WINDOWS_CLIENT_CLAIM_NOT_CORE_HASHED`` - Core cannot read the Windows file (for
  example a 46 MB LoRA on ``D:``). Core records the SHA-256 the Windows client reports
  and the Windows evidence, but never claims to have verified those bytes.

Reference eligibility is not GPU authorization; nothing here queues work.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from picotoopet_core.db.database import Database
from picotoopet_core.domain.storypack_assets import _verify_managed_object

# kind (Owner vocabulary) -> existing intake role -> existing artifact_type
ASSET_KIND_ROLES: dict[str, str] = {
    "character_master": "character",
    "scene_master": "scene",
    "identity_lock": "style",
    "lora": "lora",
    "workflow": "workflow",
}
ARTIFACT_TYPE_KINDS: dict[str, str] = {
    f"storypack_{role}": kind for kind, role in ASSET_KIND_ROLES.items()
}
CORE_COPY_KINDS = frozenset({"character_master", "scene_master", "identity_lock"})
WINDOWS_CLAIM_KINDS = frozenset({"lora", "workflow"})

CORE_COPY = "CORE_HASHED_MANAGED_COPY"
WINDOWS_CLAIM = "WINDOWS_CLIENT_CLAIM_NOT_CORE_HASHED"
NO_MANAGED_COPY = "RECORD_WITHOUT_MANAGED_COPY"

OWNER_APPROVAL_TYPE = "storypack.asset_owner_approval.v1"
_SCOPE_SCHEMA = "storypack_asset_owner_approval.v1"
_PRODUCTION_USE = "storypack.reference.v1"

# Windows-claim kinds never send bytes to Core; bounds are sanity limits only.
_CLAIM_MEDIA: dict[str, tuple[frozenset[str], int]] = {
    "lora": (frozenset({"application/octet-stream"}), 4 * 1024 * 1024 * 1024),
    "workflow": (
        frozenset({"application/json", "text/x-python", "text/plain"}),
        2 * 1024 * 1024,
    ),
}
_CORE_VERIFY_LIMIT = 64 * 1024 * 1024
_CORE_ARTIFACT_ID = re.compile(r"^asset-[0-9a-f]{64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def storypack_artifact_id(project_id: str, role: str, digest: str) -> str:
    """The deterministic per-project/role/content ID already used by local intake."""
    scoped = json.dumps([project_id, role, digest], separators=(",", ":"))
    return "asset-" + hashlib.sha256(scoped.encode("utf-8")).hexdigest()


class WindowsByteEvidenceV1(BaseModel):
    """What the Windows client says it did. Bound into approvals; never Core proof."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["windows_full_file_sha256"]
    verified_at: AwareDatetime
    verifier: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,119}$")
    file_name: str = Field(min_length=1, max_length=255)

    @field_validator("file_name")
    @classmethod
    def _basename_only(cls, value: str) -> str:
        # Private Windows paths stay on Windows; Core keeps only a bare file name.
        if (any(mark in value for mark in ("/", "\\", ":"))
                or value in (".", "..") or value != value.strip()
                or any(ord(char) < 32 for char in value)):
            raise ValueError("WINDOWS_EVIDENCE_FILE_NAME_INVALID")
        return value


class WindowsClaimRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=1, max_length=100)
    asset_kind: Literal["character_master", "scene_master", "identity_lock", "lora", "workflow"]
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    size_bytes: int = Field(gt=0)
    media_type: str = Field(min_length=1, max_length=100)
    windows_evidence: WindowsByteEvidenceV1
    confirmed: Literal[True]


class OwnerApprovalRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    windows_evidence: WindowsByteEvidenceV1 | None = None
    expires_seconds: int = Field(default=3600, ge=60, le=86400)


def _byte_provenance(kind: str, row: object) -> str:
    if row["stored_object_hash"] is None:
        return WINDOWS_CLAIM if kind in WINDOWS_CLAIM_KINDS else NO_MANAGED_COPY
    return CORE_COPY


def _row(database: Database, artifact_id: str):
    return database.fetchone("SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,))


def _expected_scope(row: object, kind: str, evidence: dict | None) -> dict[str, object]:
    return {
        "schema_version": _SCOPE_SCHEMA,
        "project_id": row["project_id"],
        "artifact_id": row["artifact_id"],
        "asset_kind": kind,
        "sha256": row["sha256"],
        "size_bytes": row["size_bytes"],
        "media_type": row["media_type"],
        "byte_provenance": _byte_provenance(kind, row),
        "windows_evidence": evidence,
        "production_use": _PRODUCTION_USE,
        "grants_gpu_post": False,
    }


_LATEST_APPROVAL_SQL = (
    "SELECT * FROM approvals WHERE approval_type = ? AND task_id IS NULL "
    "AND json_extract(scope_json, '$.artifact_id') = ? "
    "ORDER BY requested_at DESC, rowid DESC LIMIT 1"
)


def _latest_approval(connection, artifact_id: str):
    return connection.execute(
        _LATEST_APPROVAL_SQL, (OWNER_APPROVAL_TYPE, artifact_id)
    ).fetchone()


def owner_approval_status(database: Database, row: object) -> tuple[str, str | None]:
    """Fail-closed read of the latest existing approval bound to this exact artifact."""
    kind = ARTIFACT_TYPE_KINDS.get(row["artifact_type"])
    approval = database.fetchone(
        _LATEST_APPROVAL_SQL, (OWNER_APPROVAL_TYPE, row["artifact_id"])
    )
    if approval is None:
        return "NOT_REQUESTED", None
    approval_id = approval["approval_id"]
    status = approval["status"]
    expires_at = datetime.fromisoformat(approval["expires_at"])
    if status == "Pending":
        return ("EXPIRED" if expires_at <= datetime.now(UTC) else "PENDING"), approval_id
    if status != "Approved":
        return {"Rejected": "REJECTED", "Revoked": "REVOKED"}.get(status, "EXPIRED"), approval_id
    try:
        scope = json.loads(approval["scope_json"])
        resolved_at = datetime.fromisoformat(approval["resolved_at"])
    except (TypeError, ValueError):
        return "SCOPE_MISMATCH", approval_id
    evidence = scope.get("windows_evidence")
    expected = _expected_scope(row, kind, evidence)
    if (scope != expected or not approval["resolved_by"] or resolved_at > expires_at
            or (expected["byte_provenance"] == WINDOWS_CLAIM and not evidence)):
        return "SCOPE_MISMATCH", approval_id
    return "APPROVED", approval_id


_REASONS = {
    "NOT_REQUESTED": "OWNER_APPROVAL_NOT_REQUESTED",
    "PENDING": "OWNER_APPROVAL_PENDING",
    "REJECTED": "OWNER_APPROVAL_REJECTED",
    "REVOKED": "OWNER_APPROVAL_REVOKED",
    "EXPIRED": "OWNER_APPROVAL_EXPIRED",
    "SCOPE_MISMATCH": "OWNER_APPROVAL_SCOPE_MISMATCH",
    "APPROVED": "OWNER_APPROVED",
}


def production_eligibility(
    database: Database, artifact_id: str, *, objects_dir: Path
) -> dict[str, object]:
    """Reference eligibility only. Never a GPU grant; always requires a Windows byte check."""
    result: dict[str, object] = {
        "artifact_id": artifact_id,
        "asset_kind": None,
        "byte_provenance": None,
        "owner_approval_status": "NOT_REQUESTED",
        "approval_id": None,
        "eligible": False,
        "reason": "ARTIFACT_NOT_REGISTERED",
        "core_verified_bytes": False,
        # Core never controls the Windows file; the executor re-hashes before use.
        "requires_windows_byte_check_before_use": True,
        "gpu_post_authorized": False,
    }
    row = _row(database, artifact_id)
    if row is None:
        return result
    kind = ARTIFACT_TYPE_KINDS.get(row["artifact_type"])
    if kind is None:
        result["reason"] = "ARTIFACT_NOT_STORYPACK_ASSET"
        return result
    result["asset_kind"] = kind
    provenance = _byte_provenance(kind, row)
    result["byte_provenance"] = provenance
    if not isinstance(row["sha256"], str) or _SHA256.fullmatch(row["sha256"]) is None:
        result["reason"] = "RECORD_HASH_MISSING"
        return result
    if provenance == NO_MANAGED_COPY:
        result["reason"] = "CORE_COPY_MISSING"
        return result
    if provenance == CORE_COPY:
        _, verified, _ = _verify_managed_object(
            objects_dir, row["stored_object_hash"], row["sha256"], _CORE_VERIFY_LIMIT
        )
        result["core_verified_bytes"] = verified
        if not verified:
            result["reason"] = "CORE_COPY_INTEGRITY_FAILED"
            return result
    status, approval_id = owner_approval_status(database, row)
    result["owner_approval_status"] = status
    result["approval_id"] = approval_id
    result["reason"] = _REASONS[status]
    result["eligible"] = status == "APPROVED"
    return result


def find_by_sha256(
    database: Database, sha256: str, *, objects_dir: Path, project_id: str | None = None
) -> dict[str, object]:
    """Full-digest lookup of real StoryPack artifacts. Never invents an ID."""
    digest = sha256.lower()
    if _SHA256.fullmatch(digest) is None:
        raise ValueError("ASSET_SHA256_INVALID")
    placeholders = ",".join("?" for _ in ARTIFACT_TYPE_KINDS)
    query = (
        "SELECT * FROM artifacts WHERE lower(sha256) = ? "
        f"AND artifact_type IN ({placeholders})"
    )
    params: list[object] = [digest, *ARTIFACT_TYPE_KINDS]
    if project_id is not None:
        query += " AND project_id = ?"
        params.append(project_id)
    rows = database.fetchall(query + " ORDER BY created_at, artifact_id", tuple(params))
    matches = []
    for row in rows:
        state = production_eligibility(database, row["artifact_id"], objects_dir=objects_dir)
        matches.append({
            "artifact_id": row["artifact_id"],
            "project_id": row["project_id"],
            "asset_kind": state["asset_kind"],
            "artifact_type": row["artifact_type"],
            "size_bytes": row["size_bytes"],
            "media_type": row["media_type"],
            "byte_provenance": state["byte_provenance"],
            "core_verified_bytes": state["core_verified_bytes"],
            "owner_approval_status": state["owner_approval_status"],
            "production_eligible": state["eligible"],
        })
    return {"sha256": digest, "match_count": len(matches), "matches": matches}


def register_windows_claim(database: Database, request: WindowsClaimRequestV1) -> dict:
    """Record a Windows-verified digest for a file Core cannot read. No bytes, no approval."""
    kind = request.asset_kind
    if kind not in WINDOWS_CLAIM_KINDS:
        # Images and the identity lock are small enough to be hashed by Core itself.
        raise ValueError("ASSET_KIND_REQUIRES_CORE_COPY")
    media_types, max_bytes = _CLAIM_MEDIA[kind]
    if request.media_type not in media_types:
        raise ValueError("ASSET_MEDIA_INVALID")
    if request.size_bytes > max_bytes:
        raise ValueError("ASSET_SIZE_INVALID")

    digest = request.sha256.lower()
    role = ASSET_KIND_ROLES[kind]
    artifact_type = f"storypack_{role}"
    artifact_id = storypack_artifact_id(request.project_id, role, digest)
    with database.transaction() as connection:
        project = connection.execute(
            "SELECT classification, status FROM projects WHERE project_id = ?",
            (request.project_id,),
        ).fetchone()
        if project is None or project["status"] != "Active":
            raise ValueError("ASSET_PROJECT_UNAVAILABLE")
        row = connection.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if row is not None:
            expected = {
                "project_id": request.project_id, "artifact_type": artifact_type,
                "classification": project["classification"],
                "media_type": request.media_type, "size_bytes": request.size_bytes,
                "sha256": digest, "stored_object_hash": None, "source_path": None,
                "is_original": 0, "cloud_policy": "local_only",
            }
            if any(row[key] != value for key, value in expected.items()):
                raise ValueError("ASSET_REPLAY_CONFLICT")
        else:
            connection.execute(
                """INSERT INTO artifacts
                   (artifact_id, project_id, artifact_type, classification,
                    source_path, stored_object_hash, media_type, size_bytes,
                    sha256, is_original, cloud_policy, created_at)
                   VALUES (?, ?, ?, ?, NULL, NULL, ?, ?, ?, 0, 'local_only', ?)""",
                (artifact_id, request.project_id, artifact_type, project["classification"],
                 request.media_type, request.size_bytes, digest,
                 datetime.now(UTC).isoformat()),
            )

    return {
        "contract": "picotoo.storypack.windows-byte-claim.v1",
        "artifact_id": artifact_id,
        "project_id": request.project_id,
        "asset_kind": kind,
        "sha256": digest,
        "size_bytes": request.size_bytes,
        "media_type": request.media_type,
        "registration": "REPLAY" if row is not None else "CREATED",
        "byte_provenance": WINDOWS_CLAIM,
        "core_verified_bytes": False,
        "windows_evidence": request.windows_evidence.model_dump(mode="json"),
        "owner_approved": False,
        "can_queue": False,
        "gpu_post_authorized": False,
    }


def request_owner_approval(
    database: Database,
    approvals,
    artifact_id: str,
    request: OwnerApprovalRequestV1,
    *,
    objects_dir: Path,
) -> dict:
    """Open (or return) one pending approval in the existing approvals table.

    Requesting is not approving: only the Owner's digest-bound Control Center decision
    can move it to Approved. This function never resolves an approval.
    """
    row = _row(database, artifact_id)
    if row is None:
        raise LookupError("ASSET_NOT_FOUND")
    kind = ARTIFACT_TYPE_KINDS.get(row["artifact_type"])
    if kind is None:
        raise ValueError("ARTIFACT_NOT_STORYPACK_ASSET")
    if row["sha256"] != request.expected_sha256.lower():
        raise ValueError("ASSET_SHA_MISMATCH")
    provenance = _byte_provenance(kind, row)
    if provenance == WINDOWS_CLAIM and request.windows_evidence is None:
        raise ValueError("ASSET_WINDOWS_EVIDENCE_REQUIRED")
    if provenance != WINDOWS_CLAIM and request.windows_evidence is not None:
        raise ValueError("ASSET_WINDOWS_EVIDENCE_NOT_APPLICABLE")
    if provenance == NO_MANAGED_COPY:
        raise ValueError("ASSET_CORE_COPY_MISSING")
    if provenance == CORE_COPY:
        _, verified, _ = _verify_managed_object(
            objects_dir, row["stored_object_hash"], row["sha256"], _CORE_VERIFY_LIMIT
        )
        if not verified:
            raise ValueError("ASSET_CORE_COPY_UNVERIFIED")

    evidence = (None if request.windows_evidence is None
                else request.windows_evidence.model_dump(mode="json"))
    scope = _expected_scope(row, kind, evidence)
    now = datetime.now(UTC)
    with database.transaction() as connection:
        latest = _latest_approval(connection, artifact_id)
        if latest is not None and (
            latest["status"] == "Approved"
            or (latest["status"] == "Pending"
                and datetime.fromisoformat(latest["expires_at"]) > now)
        ):
            if json.loads(latest["scope_json"]) != scope:
                raise ValueError("ASSET_APPROVAL_SCOPE_CONFLICT")
            approval_row = latest
            created = False
        else:
            grant = approvals.request_resource_in_transaction(
                connection, approval_type=OWNER_APPROVAL_TYPE, scope=scope,
                requested_by="authenticated-storypack-asset-api",
                expires_at=now + timedelta(seconds=request.expires_seconds), requested_at=now,
            )
            approval_row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?", (grant.approval_id,)
            ).fetchone()
            created = True
    record = approvals.get(approval_row["approval_id"])
    return {
        "approval_id": record.approval_id,
        "approval_type": record.approval_type,
        "request_digest": record.request_digest,
        "status": record.status,
        "expires_at": record.expires_at.isoformat(),
        "artifact_id": artifact_id,
        "asset_kind": kind,
        "byte_provenance": provenance,
        "registration": "CREATED" if created else "REPLAY",
        "owner_approved": record.status == "Approved",
        "gpu_post_authorized": False,
    }


def is_core_artifact_id(ref: str) -> bool:
    return _CORE_ARTIFACT_ID.fullmatch(ref) is not None


def storypack_expected_kinds(pack) -> dict[str, str]:
    """Slot -> kind for preview diagnostics. A ref used in two kinds is flagged, not guessed."""
    kinds: dict[str, str] = {}

    def put(ref: str | None, kind: str) -> None:
        if ref is None:
            return
        previous = kinds.get(ref)
        kinds[ref] = kind if previous in (None, kind) else "AMBIGUOUS_SLOT"

    for ref in (pack.character_ref, *pack.supporting_character_refs):
        put(ref, "character_master")
    for ref in (pack.scene_ref, *pack.additional_scene_refs,
                *(shot.scene_ref for shot in pack.shots)):
        put(ref, "scene_master")
    put(pack.style_ref, "identity_lock")
    return kinds
