"""Read-only StoryPack diagnostics for Mac Core's existing artifacts and managed store.

The DB row and file bytes are not proof of copyright, identity, owner approval,
or an approved MASTER. External source_path is intentionally never opened.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path

from picotoopet_core.db.database import Database

_SHA256_HEX = re.compile(r"^[a-fA-F0-9]{64}$")
_OBJECT_HASH = re.compile(r"^[0-9a-f]{64}$")
_MAX_FILE_BYTES = 64 * 1024 * 1024        # 每个对象最多核验 64 MiB。
_MAX_PREVIEW_BYTES = 128 * 1024 * 1024    # 单次请求最多读取 128 MiB。
_CHUNK_BYTES = 1024 * 1024               # 采用流式 SHA-256，不将文件整体读入 RAM。


def _verify_managed_object(
    objects_dir: Path,
    object_hash: str | None,
    declared_digest: str | None,
    remaining_bytes: int,
) -> tuple[str, bool, int]:
    """Hash only a bounded, regular, nonsymlink object within the managed store."""
    if object_hash is None:
        return "NO_MANAGED_OBJECT", False, 0
    if not isinstance(object_hash, str) or _OBJECT_HASH.fullmatch(object_hash) is None:
        return "BAD_OBJECT_DIGEST", False, 0
    if not isinstance(declared_digest, str) or declared_digest.lower() != object_hash:
        return "DIGEST_CONFLICT", False, 0

    # 只使用内容哈希构造路径；数据库 source_path 一律不可信。
    shard = objects_dir / object_hash[:2]
    target = shard / object_hash[2:]
    try:
        if objects_dir.is_symlink() or shard.is_symlink() or target.is_symlink():
            return "OBJECT_SYMLINK_BLOCKED", False, 0
        if not target.is_file():
            return "OBJECT_NOT_FOUND", False, 0
        size = target.stat().st_size
        if size > _MAX_FILE_BYTES:
            return "OBJECT_TOO_LARGE_FOR_PREVIEW", False, 0
        if size > remaining_bytes:
            return "VERIFY_BUDGET_EXCEEDED", False, 0

        # O_NOFOLLOW 防止最终文件从普通文件被竞态替换成符号链接。
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target, flags)
        with os.fdopen(descriptor, "rb") as handle:
            actual = os.fstat(handle.fileno())
            if not stat.S_ISREG(actual.st_mode):
                return "OBJECT_NOT_REGULAR", False, 0
            if actual.st_size != size:
                return "OBJECT_CHANGED_DURING_CHECK", False, 0
            digest = hashlib.sha256()
            consumed = 0
            while True:
                chunk = handle.read(_CHUNK_BYTES)
                if not chunk:
                    break
                consumed += len(chunk)
                if consumed > _MAX_FILE_BYTES or consumed > remaining_bytes:
                    return "OBJECT_TOO_LARGE_FOR_PREVIEW", False, consumed
                digest.update(chunk)
            if consumed != size:
                return "OBJECT_CHANGED_DURING_CHECK", False, consumed
    except (OSError, ValueError):
        # 不将本地路径、异常堆栈或私有设备信息发送到创作台。
        return "OBJECT_UNAVAILABLE", False, 0

    if digest.hexdigest() != object_hash:
        return "CONTENT_HASH_MISMATCH", False, consumed
    return "CONTENT_VERIFIED_UNAPPROVED", True, consumed


def inspect_recorded_asset_refs(
    database: Database,
    refs: list[str],
    *,
    managed_objects_dir: Path | None = None,
    expected_kinds: dict[str, str] | None = None,
) -> list[dict]:
    """Check artifact records and optionally hash bounded managed bytes, without writes.

    ``expected_kinds`` maps a ref to the StoryPack slot kind (character_master,
    scene_master, identity_lock). All added fields are additive and read-only; a
    missing record is explained, never replaced by an invented artifact ID.
    """
    # Lazy import: the registry module reuses this module's managed-object verifier.
    from picotoopet_core.domain.storypack_asset_registry import (
        ARTIFACT_TYPE_KINDS,
        is_core_artifact_id,
        owner_approval_status,
    )
    from picotoopet_core.domain.storypack_asset_registry import (
        _byte_provenance as byte_provenance_of,
    )

    expected_kinds = expected_kinds or {}
    checks = []
    remaining = _MAX_PREVIEW_BYTES
    for ref in dict.fromkeys(refs):
        row = database.fetchone(
            "SELECT artifact_id, project_id, artifact_type, sha256, stored_object_hash, "
            "is_original, size_bytes, media_type FROM artifacts WHERE artifact_id = ?",
            (ref,),
        )
        expected_kind = expected_kinds.get(ref)
        asset_kind = None
        provenance = None
        approval_state = "NOT_REQUESTED"
        missing_reason = None
        if row is None:
            missing_reason = (
                "ARTIFACT_NOT_REGISTERED" if is_core_artifact_id(ref)
                else "REF_IS_NOT_A_CORE_ARTIFACT_ID"
            )
            status = "RECORD_NOT_FOUND"
            recorded_sha256 = None
            has_digest = False
            is_original = False
            category = None
            managed_status = "NO_RECORD"
            integrity_verified = False
        else:
            declared_digest = row["sha256"]
            has_digest = (
                isinstance(declared_digest, str)
                and _SHA256_HEX.fullmatch(declared_digest) is not None
            )
            recorded_sha256 = declared_digest.lower() if has_digest else None
            status = "RECORDED_UNAPPROVED" if has_digest else "RECORD_HASH_MISSING"
            is_original = row["is_original"] == 1
            category = row["artifact_type"]
            asset_kind = ARTIFACT_TYPE_KINDS.get(category)
            if asset_kind is not None:
                provenance = byte_provenance_of(asset_kind, row)
                if has_digest:
                    approval_state, _ = owner_approval_status(database, row)
            if not has_digest:
                managed_status = "RECORD_HASH_MISSING"
                integrity_verified = False
            elif managed_objects_dir is None:
                managed_status = "NOT_CHECKED"
                integrity_verified = False
            else:
                managed_status, integrity_verified, bytes_read = _verify_managed_object(
                    managed_objects_dir,
                    row["stored_object_hash"],
                    declared_digest,
                    remaining,
                )
                remaining -= bytes_read

        checks.append(
            {
                "ref": ref,
                "registry_record_status": status,
                "sha256_recorded": has_digest,
                "recorded_sha256": recorded_sha256,
                "original_flag_recorded": is_original,
                "artifact_type": category,
                "managed_object_integrity": managed_status,
                # 内容哈希通过，只证明本次读取的文件字节与登记摘要一致。
                "owner_approval_verified": approval_state == "APPROVED",
                "content_integrity_verified": integrity_verified,
                "physical_file_verified": integrity_verified,
                # A preview never authorizes generation, even for approved assets.
                "usable_for_generation": False,
                "missing_reason": missing_reason,
                "expected_asset_kind": expected_kind,
                "asset_kind": asset_kind,
                "kind_check": (
                    "NOT_CHECKED" if expected_kind is None
                    else "RECORD_NOT_FOUND" if row is None
                    else "KIND_MATCHES_SLOT" if asset_kind == expected_kind
                    else "ARTIFACT_KIND_MISMATCH"
                ),
                "byte_provenance": provenance,
                "owner_approval_status": approval_state,
            }
        )

    return checks
