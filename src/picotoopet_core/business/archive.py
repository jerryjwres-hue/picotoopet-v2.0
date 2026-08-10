"""Bounded validation for untrusted Work Package v1 ZIP archives."""

from __future__ import annotations

import codecs
import hashlib
import json
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from .models import WorkPackageManifest

MAX_COMPRESSED_BYTES = 256 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_INPUT_FILES = 64
_EXECUTABLE_SUFFIXES = {
    ".app",
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".dmg",
    ".exe",
    ".js",
    ".msi",
    ".ps1",
    ".py",
    ".sh",
}


class WorkPackageArchiveError(ValueError):
    """Stable fail-closed package validation error."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ValidatedWorkPackage:
    archive_path: Path
    top_level: str
    manifest: WorkPackageManifest
    source_digest: str
    compressed_size_bytes: int
    uncompressed_size_bytes: int


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_member(name: str) -> PurePosixPath:
    if "\\" in name:
        raise WorkPackageArchiveError("unsafe_path", "backslash archive paths are forbidden")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts:
        raise WorkPackageArchiveError("unsafe_path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise WorkPackageArchiveError("unsafe_path")
    return path


def _reject_special(info: zipfile.ZipInfo) -> None:
    mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise WorkPackageArchiveError("special_file")
    if mode & 0o111:
        raise WorkPackageArchiveError("executable_payload")


def validate_work_package_archive(path: Path) -> ValidatedWorkPackage:
    """Validate archive shape and every declared input without extracting it."""

    archive_path = Path(path).resolve()
    if not archive_path.is_file():
        raise WorkPackageArchiveError("archive_missing")
    compressed_size = archive_path.stat().st_size
    if compressed_size > MAX_COMPRESSED_BYTES:
        raise WorkPackageArchiveError("archive_too_large")

    source_digest = _sha256_file(archive_path)
    try:
        archive = zipfile.ZipFile(archive_path, "r")
    except (OSError, zipfile.BadZipFile) as error:
        raise WorkPackageArchiveError("invalid_zip") from error

    with archive:
        infos = archive.infolist()
        if not infos:
            raise WorkPackageArchiveError("empty_archive")
        normalized: dict[str, zipfile.ZipInfo] = {}
        roots: set[str] = set()
        total_uncompressed = 0
        for info in infos:
            member = _normalized_member(info.filename)
            key = member.as_posix().rstrip("/")
            if key in normalized:
                raise WorkPackageArchiveError("duplicate_path")
            normalized[key] = info
            roots.add(member.parts[0])
            _reject_special(info)
            if info.file_size > MAX_SINGLE_FILE_BYTES:
                raise WorkPackageArchiveError("file_too_large")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise WorkPackageArchiveError("uncompressed_too_large")
            if not info.is_dir() and member.suffix.lower() in _EXECUTABLE_SUFFIXES:
                raise WorkPackageArchiveError("executable_payload")

        if len(roots) != 1:
            raise WorkPackageArchiveError("multiple_roots")
        top_level = next(iter(roots))
        manifest_key = f"{top_level}/work-package.json"
        manifest_info = normalized.get(manifest_key)
        if manifest_info is None or manifest_info.is_dir():
            raise WorkPackageArchiveError("manifest_missing")
        if manifest_info.file_size > MAX_MANIFEST_BYTES:
            raise WorkPackageArchiveError("manifest_too_large")
        try:
            manifest_bytes = archive.read(manifest_info)
            manifest = WorkPackageManifest.model_validate_json(manifest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
            raise WorkPackageArchiveError("manifest_invalid") from error

        if len(manifest.inputs) > MAX_INPUT_FILES:
            raise WorkPackageArchiveError("too_many_inputs")
        expected_files = {manifest_key}
        for descriptor in manifest.inputs:
            archive_key = f"{top_level}/{descriptor.path}"
            expected_files.add(archive_key)
            info = normalized.get(archive_key)
            if info is None or info.is_dir():
                raise WorkPackageArchiveError("declared_input_missing")
            if info.file_size != descriptor.size_bytes:
                raise WorkPackageArchiveError("input_size_mismatch")
            digest = hashlib.sha256()
            decoder = codecs.getincrementaldecoder("utf-8")("strict")
            try:
                with archive.open(info, "r") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                        decoder.decode(chunk, final=False)
                decoder.decode(b"", final=True)
            except UnicodeDecodeError as error:
                raise WorkPackageArchiveError("input_not_utf8") from error
            if digest.hexdigest() != descriptor.sha256:
                raise WorkPackageArchiveError("input_hash_mismatch")

        actual_files = {
            key for key, info in normalized.items() if not info.is_dir()
        }
        if actual_files != expected_files:
            raise WorkPackageArchiveError("undeclared_file")

    return ValidatedWorkPackage(
        archive_path=archive_path,
        top_level=top_level,
        manifest=manifest,
        source_digest=source_digest,
        compressed_size_bytes=compressed_size,
        uncompressed_size_bytes=total_uncompressed,
    )
