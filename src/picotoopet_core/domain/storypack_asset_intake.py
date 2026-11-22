"""Explicit local StoryPack artifact intake using the canonical Schema-24 store.

Byte registration is not an identity, rights, MASTER, or production approval.
No caller-supplied filesystem path is ever opened.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime

from picotoopet_core.db.database import Database
from picotoopet_core.domain.storypack_assets import _verify_managed_object
from picotoopet_core.results.store import ResultStore

MAX_ASSET_BYTES = 16 * 1024 * 1024
ROLES = frozenset({"character", "scene", "style"})
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
TEXT_TYPES = frozenset({"text/plain", "application/json"})


def _validate_media(data: bytes, role: str, media_type: str) -> None:
    # This is a format gate, not visual identity, decoding, or rights validation.
    if role not in ROLES:
        raise ValueError("ASSET_ROLE_INVALID")
    if not data or len(data) > MAX_ASSET_BYTES:
        raise ValueError("ASSET_SIZE_INVALID")
    if media_type == "image/png":
        valid = data.startswith(b"\x89PNG\r\n\x1a\n")
    elif media_type == "image/jpeg":
        valid = data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9")
    elif media_type == "image/webp":
        valid = len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    elif role == "style" and media_type in TEXT_TYPES:
        try:
            decoded = data.decode("utf-8-sig")
            valid = bool(decoded.strip()) and "\x00" not in decoded
            if valid and media_type == "application/json":
                valid = isinstance(json.loads(decoded), dict)
        except (UnicodeError, ValueError, RecursionError):
            valid = False
    else:
        valid = False
    if not valid:
        raise ValueError("ASSET_MEDIA_INVALID")


def _guard_store(store: ResultStore, digest: str) -> None:
    # Only canonical SHA-derived paths are allowed; reject links and special files.
    roots = (store.root, store.objects_dir, store.manifests_dir,
             store.objects_dir / digest[:2])
    for path in roots:
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError("ASSET_STORE_UNSAFE")
    for path in (store.objects_dir / digest[:2] / digest[2:],
                 store.manifests_dir / f"{digest}.json"):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError("ASSET_STORE_UNSAFE")


def import_local_asset(
    database: Database,
    store: ResultStore,
    *,
    project_id: str,
    role: str,
    media_type: str,
    declared_sha256: str,
    data: bytes,
) -> dict:
    """Store a local-only copy with a deterministic per-project/role/content ID."""
    _validate_media(data, role, media_type)
    digest = hashlib.sha256(data).hexdigest()
    if not re.fullmatch(r"[a-f0-9]{64}", declared_sha256) or digest != declared_sha256:
        raise ValueError("ASSET_HASH_MISMATCH")

    # The content key makes identical replays harmless; different bytes get a new ID.
    scoped = json.dumps([project_id, role, digest], separators=(",", ":"))
    asset_id = "asset-" + hashlib.sha256(scoped.encode("utf-8")).hexdigest()
    artifact_type = f"storypack_{role}"

    with database.transaction() as connection:
        project = connection.execute(
            "SELECT classification, status FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if project is None or project["status"] != "Active":
            raise ValueError("ASSET_PROJECT_UNAVAILABLE")

        _guard_store(store, digest)
        object_path = store.objects_dir / digest[:2] / digest[2:]
        row = connection.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?", (asset_id,)
        ).fetchone()
        if row is not None:
            expected = {
                "project_id": project_id, "artifact_type": artifact_type,
                "classification": project["classification"], "media_type": media_type,
                "size_bytes": len(data), "sha256": digest, "stored_object_hash": digest,
                "source_path": None, "is_original": 0, "cloud_policy": "local_only",
            }
            if any(row[key] != value for key, value in expected.items()):
                raise ValueError("ASSET_REPLAY_CONFLICT")

        # Never silently heal conflicting bytes or a missing previously registered object.
        if object_path.exists() or row is not None:
            _, verified, _ = _verify_managed_object(
                store.objects_dir, digest, digest, MAX_ASSET_BYTES
            )
            if not verified:
                raise ValueError("ASSET_EXISTING_OBJECT_UNVERIFIED")

        if row is None:
            # Reuse the current core store, not a separate registry or directory.
            stored = store.put_bytes(data, result_type="storypack_local_asset")
            _guard_store(store, digest)
            _, verified, _ = _verify_managed_object(
                store.objects_dir, digest, digest, MAX_ASSET_BYTES
            )
            if stored.object_hash != digest or not verified:
                raise ValueError("ASSET_STORED_BYTES_UNVERIFIED")

            # Persist only after verified bytes exist. On DB failure, an immutable
            # unreferenced content object may remain; never delete shared objects.
            connection.execute(
                """INSERT INTO artifacts
                   (artifact_id, project_id, artifact_type, classification,
                    source_path, stored_object_hash, media_type, size_bytes,
                    sha256, is_original, cloud_policy, created_at)
                   VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, 0, 'local_only', ?)""",
                (asset_id, project_id, artifact_type, project["classification"],
                 digest, media_type, len(data), digest, datetime.now(UTC).isoformat()),
            )

    return {
        "contract": "picotoo.storypack.local-asset-intake.v1",
        "artifact_id": asset_id,
        "project_id": project_id,
        "role": role,
        "sha256": digest,
        "size_bytes": len(data),
        "media_type": media_type,
        "registration": "REPLAY" if row is not None else "CREATED",
        "content_integrity_verified": True,
        "source_provenance": "OPERATOR_SUBMITTED_COPY_UNVERIFIED",
        "is_original": False,
        "cloud_policy": "local_only",
        "owner_approved": False,
        "master_approved": False,
        "can_queue": False,
        "gpu_post_authorized": False,
    }
