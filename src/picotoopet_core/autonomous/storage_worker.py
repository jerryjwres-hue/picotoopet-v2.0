"""Deterministic P4 storage maintenance over explicit autonomous managed folders."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.worker.handlers import HandlerResult

from .storage import StorageBoundaryError, StorageLifecycleManager


class StorageMaintenanceError(RuntimeError):
    """One bounded storage-maintenance request failed its fixed contract."""


class StorageMaintenanceRequest(BaseModel):
    """Server-owned P4 request; no arbitrary path is accepted from queue payloads."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    grace_hours: int = Field(default=24, ge=1, le=168)
    max_compactions: int = Field(default=20, ge=1, le=100)


class StorageMaintenanceCoordinator:
    """Clean disposable files and compress only explicitly completed managed files."""

    TASK_TYPE = "autonomous.storage_maintenance.v1"
    CAPABILITY = "storage.maintenance"

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths
        self.completed_dir = paths.autonomous_staging_dir / "completed"
        self.completed_dir.mkdir(parents=True, exist_ok=True)
        self.lifecycle = StorageLifecycleManager(paths)

    def handler(self, task: TaskRecord) -> HandlerResult:
        if task.task_type != self.TASK_TYPE:
            raise StorageMaintenanceError("unsupported storage maintenance task type")
        try:
            request = StorageMaintenanceRequest.model_validate(task.payload)
        except ValidationError as error:
            raise StorageMaintenanceError("invalid storage maintenance request") from error

        cleanup = self.lifecycle.cleanup(
            grace_period=timedelta(hours=request.grace_hours)
        )
        files_compacted = 0
        compacted_source_bytes = 0
        compacted_archive_bytes = 0
        compaction_failures = 0

        for source in self._completed_files(limit=request.max_compactions):
            try:
                source_hash = self._sha256_file(source)
                report = self.lifecycle.compact_completed(
                    source,
                    artifact_key=f"completed-{source_hash}",
                )
            except (OSError, StorageBoundaryError):
                # One malformed managed file must not authorize broader cleanup.
                compaction_failures += 1
                continue
            files_compacted += report.files_compacted
            compacted_source_bytes += report.bytes_before
            compacted_archive_bytes += report.bytes_after

        result_document = {
            "schema_version": "1.0",
            "files_compacted": files_compacted,
            "compaction_failures": compaction_failures,
            "disposable_files_deleted": cleanup.files_deleted,
            "disposable_bytes_reclaimed": cleanup.bytes_reclaimed,
            "compacted_source_bytes": compacted_source_bytes,
            "compacted_archive_bytes": compacted_archive_bytes,
            "estimated_compaction_bytes_reclaimed": max(
                0, compacted_source_bytes - compacted_archive_bytes
            ),
        }
        return HandlerResult(
            summary={
                "task_type": self.TASK_TYPE,
                "files_compacted": files_compacted,
                "files_deleted": cleanup.files_deleted,
                "bytes_reclaimed": (
                    cleanup.bytes_reclaimed
                    + max(0, compacted_source_bytes - compacted_archive_bytes)
                ),
                "compaction_failures": compaction_failures,
            },
            result_document=result_document,
            result_type=self.TASK_TYPE,
            schema_version="1.0",
        )

    def _completed_files(self, *, limit: int) -> list[Path]:
        files: list[Path] = []
        for candidate in sorted(self.completed_dir.rglob("*")):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            files.append(candidate)
            if len(files) >= limit:
                break
        return files

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
