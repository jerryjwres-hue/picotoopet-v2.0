"""Export only fresh Mac managed SHA-bound frame sources to a portable ZIP.

This is a CPU-only *data staging* component, not an Owner/GPU approval.
Only a trusted caller that has already rechecked its exact StoryPack/Owner
evidence may ask it to export. Never load paths provided by an LLM.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import zipfile
from pathlib import Path

from picotoopet_core.domain.storypack_frame_sources import _digest

_SHA = re.compile(r"^[0-9a-f]{64}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,99}$")
_MAX_FILE = 64 * 1024 * 1024
_MAX_TOTAL = 128 * 1024 * 1024
_CHUNK = 1024 * 1024


class FrameBundleError(ValueError):
    """Stable fail-closed error without revealing absolute asset paths."""


def _manifest(preflight: dict) -> dict:
    """Reject caller-forged 'verified' fields by rehashing the exact manifest."""
    if (
        preflight.get("mac_managed_content_verified") is not True
        or preflight.get("worker_local_bytes_verified") is not False
        or not isinstance(preflight.get("bindings"), list)
        or not preflight["bindings"]
    ):
        raise FrameBundleError("FRAME_BUNDLE_SOURCE_NOT_VERIFIED")

    manifest = {
        "contract": "picotoo.frame-source-manifest.v1",
        "storypack_sha256": preflight.get("storypack_sha256"),
        "owner_subject_sha256": preflight.get("owner_subject_sha256"),
        "bindings": preflight["bindings"],
    }
    if not all(
        isinstance(manifest[name], str) and _SHA.fullmatch(manifest[name])
        for name in ("storypack_sha256", "owner_subject_sha256")
    ):
        raise FrameBundleError("FRAME_BUNDLE_SUBJECT_INVALID")
    if (
        not isinstance(preflight.get("source_bindings_sha256"), str)
        or not _SHA.fullmatch(preflight["source_bindings_sha256"])
        or _digest(manifest) != preflight["source_bindings_sha256"]
    ):
        raise FrameBundleError("FRAME_BUNDLE_MANIFEST_CHANGED")

    seen: set[tuple[str, str, str]] = set()
    for binding in manifest["bindings"]:
        if not isinstance(binding, dict) or set(binding) != {
            "shot_id", "role", "asset_ref", "managed_sha256",
        }:
            raise FrameBundleError("FRAME_BUNDLE_BINDING_INVALID")
        ref, digest, shot, role = (
            binding["asset_ref"], binding["managed_sha256"],
            binding["shot_id"], binding["role"],
        )
        if (
            not isinstance(ref, str) or not _REF.fullmatch(ref)
            or not isinstance(digest, str) or not _SHA.fullmatch(digest)
            or not isinstance(shot, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", shot)
            or role not in ("first", "last")
        ):
            raise FrameBundleError("FRAME_BUNDLE_BINDING_INVALID")
        item = (shot, role, ref)
        if item in seen:
            raise FrameBundleError("FRAME_BUNDLE_BINDING_DUPLICATE")
        seen.add(item)
    return manifest


def export_frame_bundle(
    objects_dir: Path,
    preflight: dict,
    destination_zip: Path,
) -> dict:
    """Stream-verify and package content-addressed source bytes exactly once.

    This function accepts only a preflight produced for already checked Mac
    objects. It deliberately does NOT issue any device/Worker credentials.
    """
    manifest = _manifest(preflight)
    unique_hashes = sorted({item["managed_sha256"] for item in manifest["bindings"]})
    # 源对象根目录也必须是普通目录，不能通过软链接切换素材来源。
    if objects_dir.is_symlink() or not objects_dir.is_dir():
        raise FrameBundleError("FRAME_BUNDLE_MANAGED_ROOT_INVALID")
    root = objects_dir.resolve(strict=True)
    out = Path(destination_zip)
    if out.exists() or out.is_symlink():
        raise FrameBundleError("FRAME_BUNDLE_OUTPUT_ALREADY_EXISTS")
    if not out.parent.is_dir() or out.parent.is_symlink():
        raise FrameBundleError("FRAME_BUNDLE_OUTPUT_DIR_INVALID")
    if out.resolve().is_relative_to(root):
        raise FrameBundleError("FRAME_BUNDLE_OUTPUT_INSIDE_MANAGED_STORE")

    manifest_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    if len(manifest_bytes) > 128 * 1024:
        raise FrameBundleError("FRAME_BUNDLE_MANIFEST_TOO_LARGE")

    total = 0
    created = False
    try:
        with zipfile.ZipFile(out, mode="x", compression=zipfile.ZIP_STORED) as bundle:
            created = True
            bundle.writestr("manifest.json", manifest_bytes)
            for digest in unique_hashes:
                shard = root / digest[:2]
                path = shard / digest[2:]
                if shard.is_symlink() or path.is_symlink():
                    raise FrameBundleError("FRAME_BUNDLE_SOURCE_SYMLINK")
                try:
                    # No attacker-controlled path is ever read; final component
                    # cannot be substituted with a symlink during the open().
                    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                    with os.fdopen(fd, "rb") as source:
                        metadata = os.fstat(source.fileno())
                        if not stat.S_ISREG(metadata.st_mode):
                            raise FrameBundleError("FRAME_BUNDLE_SOURCE_NOT_FILE")
                        if metadata.st_size > _MAX_FILE:
                            raise FrameBundleError("FRAME_BUNDLE_OBJECT_TOO_LARGE")
                        total += metadata.st_size
                        if total > _MAX_TOTAL:
                            raise FrameBundleError("FRAME_BUNDLE_TOTAL_TOO_LARGE")
                        hasher = hashlib.sha256()
                        consumed = 0
                        with bundle.open(f"objects/{digest}", mode="w") as target:
                            while chunk := source.read(_CHUNK):
                                consumed += len(chunk)
                                if consumed > metadata.st_size:
                                    raise FrameBundleError("FRAME_BUNDLE_SOURCE_CHANGED")
                                hasher.update(chunk)
                                target.write(chunk)
                        if (
                            consumed != metadata.st_size
                            or os.fstat(source.fileno()).st_size != metadata.st_size
                            or hasher.hexdigest() != digest
                        ):
                            raise FrameBundleError("FRAME_BUNDLE_SOURCE_CHANGED")
                except OSError as exc:
                    raise FrameBundleError("FRAME_BUNDLE_SOURCE_UNAVAILABLE") from exc
    except Exception:
        # Failed export never leaves a misleading complete ZIP behind.
        if created:
            out.unlink(missing_ok=True)
        raise

    with out.open("rb") as created_bundle:
        bundle_sha256 = hashlib.file_digest(created_bundle, "sha256").hexdigest()

    return {
        "status": "SOURCE_BUNDLE_EXPORTED_NO_GPU_AUTHORITY",
        "bundle_sha256": bundle_sha256,
        "source_bindings_sha256": preflight["source_bindings_sha256"],
        "object_count": len(unique_hashes),
        "bytes": total,
        "gpu_authorized": False,
        "can_queue": False,
    }
