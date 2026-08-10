"""Mac Core business automation orchestration facade."""

from __future__ import annotations

from pathlib import Path

from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskCreate, TaskRecord
from picotoopet_core.queue.repository import QueueRepository

from .models import (
    BusinessResultPackageRecord,
    BusinessUploadSessionRecord,
    BusinessWorkPackageStatus,
    DeepAiHandoffRecord,
    WorkPackageManifest,
    WorkPackageRecord,
)
from .repository import BusinessRepository
from .store import BusinessArtifactStore
from .upload import BusinessUploadCoordinator

BUSINESS_TASK_TYPE = "business.local_intelligence.v1"
BUSINESS_CAPABILITY = "local.intelligence.v1"
_TERMINAL = {
    BusinessWorkPackageStatus.COMPLETED,
    BusinessWorkPackageStatus.NEEDS_DEEP_AI,
    BusinessWorkPackageStatus.NEEDS_HUMAN,
    BusinessWorkPackageStatus.REJECTED,
    BusinessWorkPackageStatus.FAILED,
    BusinessWorkPackageStatus.CANCELLED,
}


class BusinessAutomationService:
    """Own package identity/state; model execution remains in Mac Worker."""

    def __init__(
        self,
        repository: BusinessRepository,
        store: BusinessArtifactStore,
        queue: QueueRepository,
    ) -> None:
        self.repository = repository
        self.store = store
        self.queue = queue
        self.uploads = BusinessUploadCoordinator(repository, store)

    def prepare_upload(
        self,
        manifest: WorkPackageManifest,
        *,
        source_digest: str,
        total_size_bytes: int,
    ) -> tuple[WorkPackageRecord, BusinessUploadSessionRecord]:
        return self.uploads.prepare(
            manifest,
            source_digest=source_digest,
            total_size_bytes=total_size_bytes,
        )

    def write_chunk(
        self,
        upload_session_id: str,
        *,
        offset: int,
        expected_sha256: str,
        payload: bytes,
    ) -> BusinessUploadSessionRecord:
        return self.uploads.write_chunk(
            upload_session_id,
            offset=offset,
            expected_sha256=expected_sha256,
            payload=payload,
        )

    def finalize_upload(self, upload_session_id: str) -> WorkPackageRecord:
        package = self.uploads.finalize(upload_session_id)
        if package.status is BusinessWorkPackageStatus.READY:
            self.ensure_local_intelligence_task(package)
        return self.repository.get_work_package(package.work_package_id)

    def ensure_local_intelligence_task(self, package: WorkPackageRecord) -> TaskRecord:
        if package.package_object_relpath is None:
            raise ValueError("business package is not immutable-ready")
        return self.queue.create(
            TaskCreate(
                task_type=BUSINESS_TASK_TYPE,
                payload={
                    "work_package_id": package.work_package_id,
                    "source_digest": package.source_digest,
                    "analysis_profile": package.analysis_profile.value,
                },
                priority=100,
                resource_tag=f"business:{package.work_package_id}",
                idempotency_key=f"business:{package.work_package_id}:local-intelligence:v1",
                max_attempts=2,
                timeout_seconds=3600,
            )
        )

    def get_work_package(self, work_package_id: str) -> WorkPackageRecord:
        return self.repository.get_work_package(work_package_id)

    def list_work_packages(self, *, limit: int = 100) -> list[WorkPackageRecord]:
        return self.repository.list_work_packages(limit=min(max(limit, 1), 200))

    def cancel(self, work_package_id: str) -> WorkPackageRecord:
        package = self.repository.get_work_package(work_package_id)
        if package.status in _TERMINAL:
            return package
        tasks = [
            task
            for task in self.queue.list(limit=5000)
            if task.resource_tag == f"business:{work_package_id}"
        ]
        for task in tasks:
            if task.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
                try:
                    self.queue.transition(task.task_id, TaskStatus.CANCELLED, "business_cancelled")
                except Exception:
                    # Queue state is authoritative for task cancellation; package still converges
                    # safely to Cancelled only if the transition was no longer actionable.
                    pass
        return self.repository.transition_work_package(
            work_package_id,
            BusinessWorkPackageStatus.CANCELLED,
            finished=True,
        )

    def result_for(self, work_package_id: str) -> BusinessResultPackageRecord | None:
        return self.repository.result_for(work_package_id)

    def result_archive(self, work_package_id: str) -> Path:
        record = self.repository.result_for(work_package_id)
        if record is None:
            raise KeyError(work_package_id)
        return self.store.resolve_managed_relative(record.package_relpath)

    def handoff_for(self, work_package_id: str) -> DeepAiHandoffRecord | None:
        return self.repository.handoff_for(work_package_id)

    def handoff_archive(self, work_package_id: str) -> Path:
        record = self.repository.handoff_for(work_package_id)
        if record is None:
            raise KeyError(work_package_id)
        return self.store.resolve_managed_relative(record.package_relpath)
