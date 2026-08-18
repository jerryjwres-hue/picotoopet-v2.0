"""Safe storage lifecycle for PicotooPet-managed autonomous data only.

This module deliberately does not scan arbitrary user folders and does not
mutate the existing content-addressed ResultStore. Useful completed staging
files are compressed only after byte-for-byte verification; disposable files
are removed only from an explicit allowlisted subdirectory after a grace
period.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from picotoopet_core.config.paths import RuntimePaths


class StorageBoundaryError(RuntimeError):
    """A requested storage mutation crossed a managed/protected boundary."""


@dataclass(frozen=True, slots=True)
class StorageLifecycleReport:
    """Small audit/status projection for one compaction or cleanup pass."""

    files_compacted: int = 0
    files_deleted: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    bytes_reclaimed: int = 0
    archive_path: Path | None = None
    manifest_path: Path | None = None


_SAFE_ARTIFACT_KEY = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


class StorageLifecycleManager:
    """Mutate only the dedicated PicotooPet autonomous runtime directories."""

    def __init__(
        self,
        paths: RuntimePaths,
        *,
        protected_roots: Iterable[Path | str] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.paths = paths
        self._clock = clock or (lambda: datetime.now(UTC))
        self.autonomous_root = paths.autonomous_root.resolve()
        self.staging_root = paths.autonomous_staging_dir.resolve()
        self.disposable_root = paths.autonomous_disposable_dir.resolve()
        self.archive_root = paths.autonomous_archive_dir.resolve()
        self.protected_roots = tuple(
            Path(root).expanduser().resolve() for root in protected_roots
        )
        for protected in self.protected_roots:
            if self._overlaps(self.autonomous_root, protected):
                raise StorageBoundaryError("protected root overlaps autonomous managed root")

    def compact_completed(
        self,
        source: Path | str,
        *,
        artifact_key: str,
    ) -> StorageLifecycleReport:
        """Compress one managed completed file and delete it only after verification."""

        if not _SAFE_ARTIFACT_KEY.fullmatch(artifact_key):
            raise StorageBoundaryError("artifact_key is not a safe managed name")
        source_path = Path(source).expanduser()
        if source_path.is_symlink():
            raise StorageBoundaryError("source symlink is not allowed")
        try:
            resolved_source = source_path.resolve(strict=True)
        except FileNotFoundError as error:
            raise StorageBoundaryError("source must be an existing regular file") from error
        self._require_under_autonomous_root(resolved_source)
        if not self._is_within(resolved_source, self.staging_root):
            raise StorageBoundaryError("source is outside autonomous staging root")
        if not resolved_source.is_file():
            raise StorageBoundaryError("source must be a regular file")
        self._reject_protected(resolved_source)

        original_size = resolved_source.stat().st_size
        source_sha256 = self._sha256_file(resolved_source)
        archive_path = self.archive_root / f"{artifact_key}.gz"
        manifest_path = self.archive_root / f"{artifact_key}.manifest.json"
        self._require_mutation_target(archive_path)
        self._require_mutation_target(manifest_path)
        self.archive_root.mkdir(parents=True, exist_ok=True)

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{artifact_key}.", suffix=".partial.gz", dir=self.archive_root
        )
        os.close(descriptor)
        temporary_archive = Path(temporary_name)
        try:
            with resolved_source.open("rb") as source_handle, temporary_archive.open("wb") as raw:
                with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
                    while True:
                        chunk = source_handle.read(1024 * 1024)
                        if not chunk:
                            break
                        compressed.write(chunk)
                raw.flush()
                os.fsync(raw.fileno())

            # Verification is performed before the source or final archive is mutated.
            with gzip.open(temporary_archive, "rb") as handle:
                restored = handle.read()
            if len(restored) != original_size or hashlib.sha256(restored).hexdigest() != source_sha256:
                raise StorageBoundaryError("compressed archive verification failed")

            archive_sha256 = self._sha256_file(temporary_archive)
            os.replace(temporary_archive, archive_path)
            compressed_size = archive_path.stat().st_size
            manifest = {
                "schema_version": "1.0",
                "artifact_key": artifact_key,
                "source_name": resolved_source.name,
                "source_sha256": source_sha256,
                "original_size_bytes": original_size,
                "archive_sha256": archive_sha256,
                "archive_size_bytes": compressed_size,
                "compression": "gzip",
                "verified": True,
                "created_at": self._now().isoformat(),
            }
            self._write_json_atomic(manifest_path, manifest)
            stored_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                stored_manifest.get("verified") is not True
                or stored_manifest.get("archive_sha256") != self._sha256_file(archive_path)
            ):
                raise StorageBoundaryError("archive manifest verification failed")

            # Deletion authority is deterministic and comes only after both verifications.
            resolved_source.unlink()
            return StorageLifecycleReport(
                files_compacted=1,
                files_deleted=1,
                bytes_before=original_size,
                bytes_after=compressed_size,
                bytes_reclaimed=max(0, original_size - compressed_size),
                archive_path=archive_path,
                manifest_path=manifest_path,
            )
        finally:
            temporary_archive.unlink(missing_ok=True)

    def cleanup(self, *, grace_period: timedelta) -> StorageLifecycleReport:
        """Remove expired ordinary files only from the explicit disposable directory."""

        if grace_period.total_seconds() < 0:
            raise ValueError("grace_period must not be negative")
        cutoff = self._now().timestamp() - grace_period.total_seconds()
        files_deleted = 0
        bytes_reclaimed = 0
        if not self.disposable_root.is_dir():
            return StorageLifecycleReport()

        for candidate in sorted(self.disposable_root.rglob("*")):
            # Never follow or remove symlinks automatically, even inside managed storage.
            if candidate.is_symlink() or not candidate.is_file():
                continue
            resolved = candidate.resolve(strict=True)
            if not self._is_within(resolved, self.disposable_root):
                continue
            self._require_under_autonomous_root(resolved)
            self._reject_protected(resolved)
            stat = resolved.stat()
            if stat.st_mtime > cutoff:
                continue
            size = stat.st_size
            resolved.unlink()
            files_deleted += 1
            bytes_reclaimed += size

        return StorageLifecycleReport(
            files_deleted=files_deleted,
            bytes_before=bytes_reclaimed,
            bytes_after=0,
            bytes_reclaimed=bytes_reclaimed,
        )

    def _require_under_autonomous_root(self, path: Path) -> None:
        if not self._is_within(path, self.autonomous_root):
            raise StorageBoundaryError("path is outside autonomous managed root")

    def _require_mutation_target(self, path: Path) -> None:
        resolved_parent = path.parent.resolve()
        self._require_under_autonomous_root(resolved_parent)
        self._reject_protected(resolved_parent)

    def _reject_protected(self, path: Path) -> None:
        for protected in self.protected_roots:
            if self._overlaps(path, protected):
                raise StorageBoundaryError("protected path is not mutable")

    def _write_json_atomic(self, destination: Path, document: dict[str, object]) -> None:
        self._require_mutation_target(destination)
        data = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True

    @classmethod
    def _overlaps(cls, first: Path, second: Path) -> bool:
        return cls._is_within(first, second) or cls._is_within(second, first)
