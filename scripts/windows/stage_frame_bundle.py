"""CPU-only import of a Mac frame ZIP into existing Windows Worker sandbox.

The expected source_bindings_sha256 MUST come from a separately trusted Core
Plan, not from the ZIP itself or the untrusted LLM. This importer never queues
tasks, relaxes HOLD, runs models, or modifies existing worker scheduling.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import zipfile
from pathlib import Path

_SHA = re.compile(r"^[0-9a-f]{64}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,99}$")
_SHOT = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_CHUNK = 1024 * 1024
_MAX_SOURCE_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_BYTES = 128 * 1024 * 1024
_MAX_ARCHIVE_BYTES = _MAX_TOTAL_BYTES + 1024 * 1024
_MAX_MANIFEST_BYTES = 128 * 1024


class FrameStageError(ValueError):
    """No raw paths, tokens or private asset bytes in operator error strings."""


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise FrameStageError("FRAME_STAGE_DUPLICATE_MANIFEST_KEY")
        result[key] = value
    return result


def _sha_json(value: dict) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _check_manifest(data: bytes, expected_sha: str) -> dict:
    if len(data) > _MAX_MANIFEST_BYTES:
        raise FrameStageError("FRAME_STAGE_MANIFEST_TOO_LARGE")
    try:
        manifest = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_keys)
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise FrameStageError("FRAME_STAGE_MANIFEST_INVALID") from exc

    if not isinstance(manifest, dict) or set(manifest) != {
        "contract", "storypack_sha256", "owner_subject_sha256", "bindings",
    } or manifest["contract"] != "picotoo.frame-source-manifest.v1":
        raise FrameStageError("FRAME_STAGE_CONTRACT_INVALID")
    if not all(
        isinstance(manifest[key], str) and _SHA.fullmatch(manifest[key])
        for key in ("storypack_sha256", "owner_subject_sha256")
    ):
        raise FrameStageError("FRAME_STAGE_SUBJECT_INVALID")
    if (
        not isinstance(expected_sha, str)
        or not _SHA.fullmatch(expected_sha)
        or _sha_json(manifest) != expected_sha
    ):
        raise FrameStageError("FRAME_STAGE_EXPECTED_SOURCE_SHA_MISMATCH")
    bindings = manifest["bindings"]
    if not isinstance(bindings, list) or not 1 <= len(bindings) <= 960:
        raise FrameStageError("FRAME_STAGE_BINDINGS_INVALID")
    seen: set[tuple[str, str, str]] = set()
    for row in bindings:
        if not isinstance(row, dict) or set(row) != {
            "shot_id", "role", "asset_ref", "managed_sha256",
        }:
            raise FrameStageError("FRAME_STAGE_BINDING_INVALID")
        if (
            not isinstance(row["shot_id"], str)
            or not _SHOT.fullmatch(row["shot_id"])
            or row["role"] not in ("first", "last")
            or not isinstance(row["asset_ref"], str)
            or not _REF.fullmatch(row["asset_ref"])
            or not isinstance(row["managed_sha256"], str)
            or not _SHA.fullmatch(row["managed_sha256"])
        ):
            raise FrameStageError("FRAME_STAGE_BINDING_INVALID")
        key = (row["shot_id"], row["role"], row["asset_ref"])
        if key in seen:
            raise FrameStageError("FRAME_STAGE_BINDING_DUPLICATE")
        seen.add(key)
    return manifest


def _image_suffix(header: bytes) -> str:
    # 文件后缀只由已 SHA 绑定的真实字节决定，不信任 LLM 或 ZIP 文件名。
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return ".webp"
    raise FrameStageError("FRAME_STAGE_NOT_A_SUPPORTED_IMAGE")


def _hash_existing(path: Path, expected: str) -> bool:
    if path.is_symlink():
        raise FrameStageError("FRAME_STAGE_EXISTING_SYMLINK")
    if not path.exists():
        return False
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                raise FrameStageError("FRAME_STAGE_EXISTING_NOT_REGULAR")
            sha = hashlib.sha256()
            used = 0
            while data := file.read(_CHUNK):
                used += len(data)
                if used > _MAX_SOURCE_BYTES:
                    raise FrameStageError("FRAME_STAGE_EXISTING_TOO_LARGE")
                sha.update(data)
            if sha.hexdigest() != expected:
                raise FrameStageError("FRAME_STAGE_EXISTING_SHA_MISMATCH")
            return True
    except OSError as exc:
        raise FrameStageError("FRAME_STAGE_EXISTING_UNAVAILABLE") from exc


def _prepare_staging_root(worker_root: Path) -> Path:
    root = Path(worker_root)
    if root.is_symlink() or not root.is_dir():
        raise FrameStageError("FRAME_STAGE_WORKER_ROOT_INVALID")
    root = root.resolve(strict=True)
    folder = root
    for part in ("_queue", "executor_bridge", "staged_references"):
        folder = folder / part
        if folder.is_symlink():
            raise FrameStageError("FRAME_STAGE_STAGING_SYMLINK")
        folder.mkdir(exist_ok=True)
        if not folder.is_dir() or folder.is_symlink():
            raise FrameStageError("FRAME_STAGE_STAGING_NOT_DIRECTORY")
    if not folder.resolve().is_relative_to(root):
        raise FrameStageError("FRAME_STAGE_OUTSIDE_WORKER_SANDBOX")
    return folder


def stage_frame_bundle(
    bundle_path: Path,
    *,
    expected_source_bindings_sha256: str,
    worker_root: Path,
) -> dict:
    """Verify a complete ZIP, then stage SHA-named images into Worker sandbox.

    No unverified archive entry controls any output filename or destination.
    The return value is a DATA receipt, explicitly not production authorization.
    """
    bundle_path = Path(bundle_path)
    if bundle_path.is_symlink() or not bundle_path.is_file():
        raise FrameStageError("FRAME_STAGE_BUNDLE_NOT_REGULAR")
    if bundle_path.stat().st_size > _MAX_ARCHIVE_BYTES:
        raise FrameStageError("FRAME_STAGE_BUNDLE_TOO_LARGE")
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)) or "manifest.json" not in names:
                raise FrameStageError("FRAME_STAGE_ARCHIVE_ENTRIES_INVALID")
            for entry in entries:
                if (
                    entry.is_dir() or entry.compress_type != zipfile.ZIP_STORED
                    or bool(entry.flag_bits & 0x1)
                    or stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFLNK
                ):
                    raise FrameStageError("FRAME_STAGE_ARCHIVE_ENTRY_UNSAFE")

            manifest_entry = archive.getinfo("manifest.json")
            if manifest_entry.file_size > _MAX_MANIFEST_BYTES:
                raise FrameStageError("FRAME_STAGE_MANIFEST_TOO_LARGE")
            manifest = _check_manifest(
                archive.read(manifest_entry),
                expected_source_bindings_sha256,
            )
            hashes = sorted({
                item["managed_sha256"] for item in manifest["bindings"]
            })
            if not hashes or len(hashes) > 64 or set(names) != {
                "manifest.json", *(f"objects/{digest}" for digest in hashes),
            }:
                raise FrameStageError("FRAME_STAGE_ARCHIVE_CONTENTS_UNEXPECTED")
            if any(
                archive.getinfo(f"objects/{digest}").file_size > _MAX_SOURCE_BYTES
                for digest in hashes
            ) or sum(
                archive.getinfo(f"objects/{digest}").file_size
                for digest in hashes
            ) > _MAX_TOTAL_BYTES:
                raise FrameStageError("FRAME_STAGE_UNCOMPRESSED_BUDGET_EXCEEDED")

            # Validate before any writing. All images are content-addressed,
            # then stage into the existing root used by executor_bridge.py.
            staging = _prepare_staging_root(worker_root)
            refs = {}
            verified_bytes = 0
            for digest in hashes:
                temp_name = None
                try:
                    with archive.open(f"objects/{digest}", "r") as source:
                        handle, temp_name = tempfile.mkstemp(
                            prefix=".frame-", suffix=".tmp", dir=staging
                        )
                        sha = hashlib.sha256()
                        count = 0
                        first = b""
                        with os.fdopen(handle, "wb") as output:
                            while chunk := source.read(_CHUNK):
                                if not first:
                                    first = chunk[:16]
                                count += len(chunk)
                                if count > _MAX_SOURCE_BYTES:
                                    raise FrameStageError("FRAME_STAGE_OBJECT_TOO_LARGE")
                                sha.update(chunk)
                                output.write(chunk)
                            output.flush()
                            os.fsync(output.fileno())
                        if (
                            count != archive.getinfo(f"objects/{digest}").file_size
                            or sha.hexdigest() != digest
                        ):
                            raise FrameStageError("FRAME_STAGE_OBJECT_SHA_MISMATCH")
                        suffix = _image_suffix(first)
                        destination = staging / f"{digest}{suffix}"
                        if not _hash_existing(destination, digest):
                            try:
                                # Link is atomic and never replaces existing data.
                                # Retain immutable digest-derived filenames.
                                os.link(temp_name, destination)
                            except FileExistsError:
                                _hash_existing(destination, digest)
                        # Recheck final bytes before including any consumer path.
                        if not _hash_existing(destination, digest):
                            raise FrameStageError("FRAME_STAGE_OBJECT_UNAVAILABLE")
                        verified_bytes += count
                        refs[digest] = (
                            f"../_queue/executor_bridge/staged_references/{digest}{suffix}"
                        )
                finally:
                    if temp_name is not None:
                        Path(temp_name).unlink(missing_ok=True)
    except FrameStageError:
        raise
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, EOFError) as exc:
        raise FrameStageError("FRAME_STAGE_BUNDLE_INVALID") from exc

    return {
        "contract": "picotoo.frame-staging-receipt.v1",
        "status": "WINDOWS_BYTES_VERIFIED_NO_PRODUCTION_AUTHORITY",
        "source_bindings_sha256": expected_source_bindings_sha256,
        "storypack_sha256": manifest["storypack_sha256"],
        "owner_subject_sha256": manifest["owner_subject_sha256"],
        "verified_bytes": verified_bytes,
        "worker_local_bytes_verified": True,
        "worker_ref_paths_by_digest": refs,
        "bindings": [
            {
                "shot_id": row["shot_id"],
                "role": row["role"],
                "asset_ref": row["asset_ref"],
                "managed_sha256": row["managed_sha256"],
                "worker_ref": refs[row["managed_sha256"]],
            }
            for row in manifest["bindings"]
        ],
        "can_queue": False,
        "gpu_authorized": False,
    }
