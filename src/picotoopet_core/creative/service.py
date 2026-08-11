"""Mac Core Creative Intelligence orchestration facade."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from picotoopet_core.domain.enums import TaskStatus
from picotoopet_core.domain.models import TaskCreate, TaskRecord
from picotoopet_core.queue.repository import QueueRepository

from .models import (
    CreativeDeepAiHandoffRecord,
    CreativeJobRecord,
    CreativeJobStatus,
    CreativePackageRecord,
    CreativeProfile,
)
from .profiles import creative_profile_definition
from .repository import CreativeRepository
from .source import CreativeSourceNormalizer
from .store import CreativeArtifactStore

CREATIVE_TASK_TYPE = "creative.content_plan.v1"
CREATIVE_CAPABILITY = "creative.intelligence.v1"
_TERMINAL = {
    CreativeJobStatus.CREATIVE_READY,
    CreativeJobStatus.NEEDS_DEEP_AI,
    CreativeJobStatus.NEEDS_HUMAN,
    CreativeJobStatus.REJECTED,
    CreativeJobStatus.FAILED,
    CreativeJobStatus.CANCELLED,
}


class CreativeIntelligenceService:
    def __init__(
        self,
        *,
        repository: CreativeRepository,
        source_normalizer: CreativeSourceNormalizer,
        store: CreativeArtifactStore,
        queue: QueueRepository,
    ) -> None:
        self.repository = repository
        self.source_normalizer = source_normalizer
        self.store = store
        self.queue = queue

    @staticmethod
    def _digest(value: object) -> str:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def create_job(
        self,
        *,
        source_result_package_ids: list[str],
        creative_profile: str,
        creative_objective: str | None,
        idempotency_key: str,
    ) -> CreativeJobRecord:
        profile = creative_profile_definition(creative_profile)
        source_set = self.source_normalizer.normalize_source_set(source_result_package_ids)
        objective = creative_objective.strip() if creative_objective and creative_objective.strip() else None
        if objective is not None and len(objective) > 2000:
            raise ValueError("CREATIVE_OBJECTIVE_TOO_LARGE")
        objective_digest = self._digest({"objective": objective or ""})
        combined_source_digest = self._digest(
            {
                "source_set_digest": source_set.source_set_digest,
                "project_key": source_set.project_key,
                "profile": profile.profile_id,
                "objective_digest": objective_digest,
                "templates": [stage.template_version for stage in profile.stages],
            }
        )
        job = self.repository.create_job(
            creative_job_id=str(uuid4()),
            project_key=source_set.project_key,
            creative_profile=CreativeProfile.CONTENT_PLAN_V1,
            creative_objective=objective,
            objective_digest=objective_digest,
            source_set_digest=combined_source_digest,
            idempotency_key=idempotency_key,
        )
        self.source_normalizer.persist_source_set(job.creative_job_id, source_set.model_copy(update={"source_set_digest": combined_source_digest}))
        self.ensure_task(job)
        return self.repository.get_job(job.creative_job_id)

    def ensure_task(self, job: CreativeJobRecord) -> TaskRecord:
        return self.queue.create(
            TaskCreate(
                task_type=CREATIVE_TASK_TYPE,
                payload={
                    "creative_job_id": job.creative_job_id,
                    "source_set_digest": job.source_set_digest,
                    "creative_profile": job.creative_profile.value,
                },
                priority=100,
                resource_tag=f"creative:{job.creative_job_id}",
                idempotency_key=f"creative:{job.creative_job_id}:content-plan:v1",
                max_attempts=2,
                timeout_seconds=3600,
            )
        )

    def list_eligible_sources(self):  # type: ignore[no-untyped-def]
        return self.source_normalizer.list_eligible_sources()

    def get_job(self, creative_job_id: str) -> CreativeJobRecord:
        return self.repository.get_job(creative_job_id)

    def list_jobs(self, *, limit: int = 100) -> list[CreativeJobRecord]:
        return self.repository.list_jobs(limit=limit)

    def cancel(self, creative_job_id: str) -> CreativeJobRecord:
        job = self.repository.get_job(creative_job_id)
        if job.status in _TERMINAL:
            return job
        for task in self.queue.list(limit=5000):
            if task.resource_tag != f"creative:{creative_job_id}":
                continue
            if task.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
                try:
                    self.queue.transition(task.task_id, TaskStatus.CANCELLED, "creative_cancelled")
                except Exception:
                    pass
        return self.repository.transition_job(creative_job_id, CreativeJobStatus.CANCELLED, finished=True)

    def get_package(self, creative_job_id: str) -> CreativePackageRecord | None:
        return self.repository.package_for(creative_job_id)

    def package_archive(self, creative_job_id: str) -> Path:
        record = self.get_package(creative_job_id)
        if record is None:
            raise KeyError(creative_job_id)
        return self.store.resolve_managed_relative(record.package_relpath)

    def get_handoff(self, creative_job_id: str) -> CreativeDeepAiHandoffRecord | None:
        return self.repository.handoff_for(creative_job_id)

    def handoff_archive(self, creative_job_id: str) -> Path:
        record = self.get_handoff(creative_job_id)
        if record is None:
            raise KeyError(creative_job_id)
        return self.store.resolve_managed_relative(record.package_relpath)
