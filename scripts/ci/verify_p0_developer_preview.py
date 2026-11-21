"""Verify every byte of the unsigned P0 developer preview without executing it.

This tool deliberately does NOT certify production installation, Owner consent,
GPU access, signed binaries, model presence, or formal Maotai sprite acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

_CHUNK = 1024 * 1024
_MAX_FILES = 2048
_MAX_FILE_BYTES = 768 * 1024 * 1024
_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED = {
    "app/Picotoo Pet AI.exe",
    "app/product-version.txt",
    "Prepare-P0ThreeShotHold.ps1",
    "CONNECT_MAC_SECURE.vbs",
    "Start-SecureMacTunnel.ps1",
    "README_P0_DEVELOPER_PREVIEW.txt",
}


class PreviewVerificationError(ValueError):
    """Invalid, missing or misleading developer-preview evidence."""


def _sha256_stream(source) -> tuple[str, int]:
    """Compute real bytes rather than trusting ZIP header CRC or untrusted metadata."""

    digest = hashlib.sha256()
    consumed = 0
    while chunk := source.read(_CHUNK):
        consumed += len(chunk)
        if consumed > _MAX_FILE_BYTES:
            raise PreviewVerificationError("FILE_TOO_LARGE")
        digest.update(chunk)
    return digest.hexdigest(), consumed


def _strict_pairs(pairs):
    """Reject duplicate JSON keys that could hide authorization settings."""

    result = {}
    for key, value in pairs:
        if key in result:
            raise PreviewVerificationError("DUPLICATE_MANIFEST_KEY")
        result[key] = value
    return result


def _safe_name(name: str) -> bool:
    """Allow only normalized, relative, forward-slashed package paths."""

    if not name or "\\" in name or "\x00" in name or name.startswith("/"):
        return False
    parts = PurePosixPath(name).parts
    return bool(parts) and not any(part in (".", "..") for part in name.split("/")) \
        and not name.endswith(":") and ":" not in parts[0]


def verify_preview_archive(
    archive: Path,
    receipt: Path,
    *,
    expected_source_sha: str,
    expected_run_id: str,
) -> dict:
    """Check exact GitHub source identity, all ZIP members and HOLD/release claims."""

    if not _COMMIT.fullmatch(expected_source_sha):
        raise PreviewVerificationError("EXPECTED_SOURCE_SHA_INVALID")
    if not expected_run_id.isdecimal() or not expected_run_id:
        raise PreviewVerificationError("EXPECTED_RUN_ID_INVALID")
    if not archive.is_file() or not receipt.is_file():
        raise PreviewVerificationError("ARCHIVE_OR_RECEIPT_MISSING")

    # 校验 ZIP 自身 SHA；GitHub Artifact 容器包不是内部 P0 ZIP 的哈希证明。
    with archive.open("rb") as handle:
        archive_hash, archive_size = _sha256_stream(handle)
    if not _SHA256.fullmatch(archive_hash):
        raise PreviewVerificationError("ARCHIVE_DIGEST_INVALID")
    receipt_text = receipt.read_text(encoding="ascii").strip()
    if receipt_text != f"{archive_hash}  {archive.name}":
        raise PreviewVerificationError("ARCHIVE_SHA256_RECEIPT_MISMATCH")

    try:
        with zipfile.ZipFile(archive, "r") as zip_file:
            raw_entries = zip_file.infolist()
            entries: dict[str, zipfile.ZipInfo] = {}
            seen: set[str] = set()
            total = 0
            for entry in raw_entries:
                name = entry.filename
                if not _safe_name(name.rstrip("/") if entry.is_dir() else name):
                    raise PreviewVerificationError("UNSAFE_ZIP_PATH")
                normalized = name.rstrip("/").casefold()
                if normalized in seen:
                    raise PreviewVerificationError("DUPLICATE_OR_CASE_COLLIDING_PATH")
                seen.add(normalized)
                if entry.is_dir():
                    continue

                # 不允许符号链接/特殊文件伪装普通程序，也不允许压缩炸弹。
                unix_mode = (entry.external_attr >> 16) & 0xFFFF
                kind = stat.S_IFMT(unix_mode)
                if kind not in (0, stat.S_IFREG):
                    raise PreviewVerificationError("ZIP_SPECIAL_FILE")
                if entry.file_size > _MAX_FILE_BYTES:
                    raise PreviewVerificationError("ZIP_MEMBER_TOO_LARGE")
                total += entry.file_size
                if total > _MAX_TOTAL_BYTES or len(entries) >= _MAX_FILES:
                    raise PreviewVerificationError("ZIP_RESOURCE_BUDGET_EXCEEDED")
                entries[name] = entry

            if "preview-manifest.json" not in entries:
                raise PreviewVerificationError("MANIFEST_MISSING")
            if entries["preview-manifest.json"].file_size > 1024 * 1024:
                raise PreviewVerificationError("MANIFEST_TOO_LARGE")
            with zip_file.open(entries["preview-manifest.json"]) as handle:
                manifest = json.loads(
                    handle.read().decode("utf-8-sig"),
                    object_pairs_hook=_strict_pairs,
                )
            if not isinstance(manifest, dict):
                raise PreviewVerificationError("MANIFEST_NOT_OBJECT")

            # 核验只读预览身份，绝不把内部便携构建认证成正式安装包。
            expected = {
                "schema_version": "p0-three-shot-developer-preview.v1",
                "source_sha": expected_source_sha,
                "github_run_id": expected_run_id,
                "build_target": "win-x64-self-contained",
                "artifact_kind": "unsigned-portable-developer-preview",
                "executable": "app/Picotoo Pet AI.exe",
                "hold_script": "Prepare-P0ThreeShotHold.ps1",
                "connection_launcher": "CONNECT_MAC_SECURE.vbs",
                "connection_script": "Start-SecureMacTunnel.ps1",
            }
            if any(str(manifest.get(key)) != value for key, value in expected.items()):
                raise PreviewVerificationError("MANIFEST_IDENTITY_MISMATCH")
            if manifest.get("user_install_allowed") is not False \
                or manifest.get("formal_release_pass") is not False:
                raise PreviewVerificationError("UNAUTHORIZED_RELEASE_CLAIM")
            if not isinstance(manifest.get("product_version"), str) \
                or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){3}", manifest["product_version"]):
                raise PreviewVerificationError("PRODUCT_VERSION_INVALID")

            records = manifest.get("files")
            if not isinstance(records, list) or not records:
                raise PreviewVerificationError("FILE_MANIFEST_MISSING")
            listed: set[str] = set()
            for item in records:
                if not isinstance(item, dict):
                    raise PreviewVerificationError("FILE_RECORD_INVALID")
                name = item.get("path")
                if not isinstance(name, str) or name not in entries \
                    or name == "preview-manifest.json" or not _safe_name(name):
                    raise PreviewVerificationError("FILE_ENTRY_INVALID")
                if name in listed:
                    raise PreviewVerificationError("DUPLICATE_FILE_MANIFEST_RECORD")
                listed.add(name)
                expected_hash = item.get("sha256")
                expected_bytes = item.get("size_bytes")
                if not isinstance(expected_hash, str) or not _SHA256.fullmatch(expected_hash):
                    raise PreviewVerificationError("FILE_HASH_RECORD_INVALID")
                if type(expected_bytes) is not int or expected_bytes < 0:
                    raise PreviewVerificationError("FILE_SIZE_RECORD_INVALID")
                with zip_file.open(entries[name]) as handle:
                    actual_hash, actual_bytes = _sha256_stream(handle)
                if expected_hash != actual_hash or expected_bytes != actual_bytes:
                    raise PreviewVerificationError("FILE_BYTES_OR_SHA256_MISMATCH")

            if listed != set(entries) - {"preview-manifest.json"}:
                raise PreviewVerificationError("UNLISTED_ARCHIVE_MEMBER")
            if not _REQUIRED.issubset(listed):
                raise PreviewVerificationError("REQUIRED_PAYLOAD_MISSING")
            with zip_file.open("README_P0_DEVELOPER_PREVIEW.txt") as handle:
                readme = handle.read().decode("utf-8-sig")
            if "NOT a formal Release Builder output" not in readme \
                or "Desktop pet is DEFERRED and excluded from film-production scope." not in readme \
                or "Only trusted SSH public-key authentication" not in readme:
                raise PreviewVerificationError("UNSAFE_README_CLAIMS")
            with zip_file.open("app/product-version.txt") as handle:
                product_version = handle.read().decode("utf-8-sig").strip()
            if product_version != manifest["product_version"]:
                raise PreviewVerificationError("PRODUCT_VERSION_BYTES_MISMATCH")
            if entries["app/Picotoo Pet AI.exe"].file_size == 0:
                raise PreviewVerificationError("EXECUTABLE_EMPTY")
    except (OSError, zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as exc:
        raise PreviewVerificationError("UNREADABLE_ARCHIVE") from exc

    return {
        "archive_sha256": archive_hash,
        "archive_size_bytes": archive_size,
        "source_sha": expected_source_sha,
        "github_run_id": expected_run_id,
        "files_verified": len(listed),
        "formal_release_pass": False,
        "user_install_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256-receipt", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        result = verify_preview_archive(
            args.archive,
            args.sha256_receipt,
            expected_source_sha=args.source_sha,
            expected_run_id=args.run_id,
        )
    except PreviewVerificationError as exc:
        print(f"P0_PREVIEW_ARCHIVE=BLOCKED REASON={exc}", file=sys.stderr)
        return 2
    print(
        "P0_PREVIEW_ARCHIVE=PASS "
        f"SOURCE_SHA={result['source_sha']} "
        f"ZIP_SHA256={result['archive_sha256']} "
        f"FILES={result['files_verified']} "
        "FORMAL_RELEASE=BLOCKED USER_INSTALL_ALLOWED=FALSE"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
