"""Mac Core orchestration facade for the closed Windows production executor."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from picotoopet_core.creative.models import (
    CreativeJobStatus,
    CreativePackageRecord,
    CreativeQualityOutcome,
)
from picotoopet_core.creative.repository import CreativeRepository

from .compiler import compile_production_plan
from .models import (
    ProductionClaimRecord,
    ProductionEligibleCreativeRecord,
    ProductionHeartbeatRequest,
    ProductionJobCreateRequest,
    ProductionJobRecord,
    ProductionJobStatus,
    ProductionPackageRecord,
    ProductionPlan,
    ProductionTaskAttemptRequest,
    ProductionTaskCommitRequest,
    ProductionTaskRecord,
    ProductionTaskStatus,
)
from .quality import validate_task_commit
from .repository import ProductionRepository
from .store import ProductionArtifactStore


class ProductionService:
    def __init__(
        self,
        *,
        repository: ProductionRepository,
        creative_repository: CreativeRepository,
        store: ProductionArtifactStore,
    ) -> None:
        # ── Core remains the only durable state authority ───────────────────
        self.repository = repository
        self.creative_repository = creative_repository
        self.store = store

    @staticmethod
    def _digest(value: object) -> str:
        # ── Canonical digest binds immutable plans and package manifests ─────
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _creative_package_by_id(self, creative_package_id: str) -> CreativePackageRecord:
        # ── Production consumes a package identity, not a Creative Job id ───
        row = self.repository.database.fetchone(
            "SELECT * FROM creative_packages WHERE creative_package_id=?",
            (creative_package_id,),
        )
        if row is None:
            raise KeyError(creative_package_id)
        return CreativePackageRecord(
            creative_package_id=row["creative_package_id"],
            creative_job_id=row["creative_job_id"],
            source_set_digest=row["source_set_digest"],
            package_digest=row["package_digest"],
            package_relpath=row["package_relpath"],
            manifest=json.loads(row["manifest_json"]),
            quality_outcome=row["quality_outcome"],
            created_at=row["created_at"],
        )

    def list_eligible(self) -> list[ProductionEligibleCreativeRecord]:
        # ── Only unused PASS + creative_ready packages may enter production ─
        rows = self.repository.database.fetchall(
            "SELECT cp.creative_package_id,cp.creative_job_id,cj.project_key,cp.package_digest,cp.created_at "
            "FROM creative_packages cp "
            "JOIN creative_jobs cj ON cj.creative_job_id=cp.creative_job_id "
            "LEFT JOIN production_jobs pj ON pj.creative_package_id=cp.creative_package_id "
            "WHERE cp.quality_outcome='PASS' AND cj.status=? AND pj.production_job_id IS NULL "
            "ORDER BY cp.created_at DESC",
            (CreativeJobStatus.CREATIVE_READY.value,),
        )
        return [
            ProductionEligibleCreativeRecord(
                creative_package_id=row["creative_package_id"],
                creative_job_id=row["creative_job_id"],
                project_key=row["project_key"],
                package_digest=row["package_digest"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def create_job(self, request: ProductionJobCreateRequest) -> ProductionJobRecord:
        # ── Producer contributes no renderer configuration ──────────────────
        package = self._creative_package_by_id(request.creative_package_id)
        creative_job = self.creative_repository.get_job(package.creative_job_id)
        if (
            package.quality_outcome is not CreativeQualityOutcome.PASS
            or creative_job.status is not CreativeJobStatus.CREATIVE_READY
        ):
            raise ValueError("PRODUCTION_CREATIVE_PACKAGE_NOT_ELIGIBLE")

        existing = self.repository.database.fetchone(
            "SELECT production_job_id FROM production_jobs WHERE idempotency_key=?",
            (request.idempotency_key,),
        )
        production_job_id = existing["production_job_id"] if existing is not None else str(uuid4())
        plan = compile_production_plan(production_job_id, package.manifest, package.package_digest)
        plan_digest = self._digest(plan.model_dump(mode="json"))
        job = self.repository.create_job(
            production_job_id=production_job_id,
            creative_package_id=package.creative_package_id,
            creative_package_digest=package.package_digest,
            project_key=creative_job.project_key,
            production_profile=request.production_profile,
            idempotency_key=request.idempotency_key,
        )
        self.repository.save_plan(job.production_job_id, plan, plan_digest)
        return self.repository.get_job(job.production_job_id)

    def get_job(self, production_job_id: str) -> ProductionJobRecord:
        return self.repository.get_job(production_job_id)

    def list_jobs(self, *, limit: int = 100) -> list[ProductionJobRecord]:
        return self.repository.list_jobs(limit=limit)

    def get_plan(self, production_job_id: str) -> ProductionPlan:
        return self.repository.plan_for(production_job_id)

    def claim(self, production_job_id: str, executor_id: str) -> ProductionClaimRecord:
        # ── Claim returns full durable snapshots plus an unfinished-only plan ─
        claim = self.repository.claim_job(production_job_id, executor_id)
        snapshots = {task.production_task_id: task for task in claim.tasks}
        resume_tasks = []
        for planned in claim.plan.tasks:
            snapshot = snapshots.get(planned.production_task_id)
            if snapshot is None:
                raise ValueError("PRODUCTION_TASK_SNAPSHOT_MISSING")
            if snapshot.status is ProductionTaskStatus.SUCCEEDED:
                continue
            if snapshot.status in {
                ProductionTaskStatus.NEEDS_HUMAN,
                ProductionTaskStatus.FAILED,
                ProductionTaskStatus.CANCELLED,
            }:
                raise ValueError("PRODUCTION_TASK_TERMINAL_STATE")
            if snapshot.attempt_count >= self.repository.MAX_ATTEMPTS_PER_TASK:
                raise ValueError("PRODUCTION_ATTEMPT_BUDGET_EXHAUSTED")
            resume_tasks.append(planned)

        # ── A crash may happen after final task commit but before packaging ──
        if not resume_tasks and claim.tasks:
            self._finalize_if_complete(production_job_id)

        # ── Stored immutable plan is untouched; only this lease response narrows ─
        resume_plan = claim.plan.model_copy(update={"tasks": resume_tasks})
        return claim.model_copy(update={"plan": resume_plan})

    def heartbeat(self, production_job_id: str, request: ProductionHeartbeatRequest) -> ProductionJobRecord:
        return self.repository.heartbeat(
            production_job_id,
            request.executor_id,
            request.lease_token,
        )

    def mark_attempt(
        self,
        production_job_id: str,
        production_task_id: str,
        request: ProductionTaskAttemptRequest,
    ) -> ProductionTaskRecord:
        return self.repository.mark_task_attempt(
            production_job_id,
            production_task_id,
            request.executor_id,
            request.lease_token,
            request.comfy_prompt_id,
        )

    def commit_task(
        self,
        production_job_id: str,
        production_task_id: str,
        request: ProductionTaskCommitRequest,
    ) -> ProductionTaskRecord:
        # ── Validate evidence against the exact task plan before persistence ─
        task = self.repository.get_task(production_job_id, production_task_id)
        validate_task_commit(task.task_plan, request)
        committed = self.repository.commit_task_result(production_job_id, production_task_id, request)
        self._finalize_if_complete(production_job_id)
        return committed

    def cancel(self, production_job_id: str) -> ProductionJobRecord:
        job = self.repository.get_job(production_job_id)
        if job.status in {
            ProductionJobStatus.PRODUCTION_READY,
            ProductionJobStatus.NEEDS_HUMAN,
            ProductionJobStatus.FAILED,
            ProductionJobStatus.CANCELLED,
        }:
            return job
        return self.repository.transition_job(
            production_job_id,
            ProductionJobStatus.CANCELLED,
            finished=True,
            clear_lease=True,
        )

    def get_package(self, production_job_id: str) -> ProductionPackageRecord | None:
        return self.repository.package_for(production_job_id)

    def package_archive(self, production_job_id: str) -> Path:
        record = self.get_package(production_job_id)
        if record is None:
            raise KeyError(production_job_id)
        return self.store.resolve_managed_relative(record.package_relpath)

    def _finalize_if_complete(self, production_job_id: str) -> None:
        # ── production_ready requires every planned shot to be successful ───
        tasks = self.repository.list_tasks(production_job_id)
        if not tasks or any(task.status.value == "NeedsHuman" for task in tasks):
            self.repository.transition_job(
                production_job_id,
                ProductionJobStatus.NEEDS_HUMAN,
                finished=True,
                clear_lease=True,
            )
            return
        if any(task.status.value != "Succeeded" for task in tasks):
            return

        job = self.repository.get_job(production_job_id)
        if self.repository.package_for(production_job_id) is not None:
            self.repository.transition_job(
                production_job_id,
                ProductionJobStatus.PRODUCTION_READY,
                finished=True,
                clear_lease=True,
            )
            return

        self.repository.transition_job(production_job_id, ProductionJobStatus.QUALITY_CHECK)
        package_id = str(uuid4())
        payload = {
            "schema_version": "1.0",
            "production_package_id": package_id,
            "production_job_id": production_job_id,
            "creative_package_id": job.creative_package_id,
            "creative_package_digest": job.creative_package_digest,
            "production_profile": job.production_profile.value,
            "plan_digest": job.plan_digest,
            "outputs": [
                {
                    "production_task_id": task.production_task_id,
                    "shot_id": task.shot_id,
                    "workflow_id": task.workflow_id,
                    "comfy_prompt_id": task.comfy_prompt_id,
                    "output_relpath": task.output_relpath,
                    "output_sha256": task.output_sha256,
                    "output_bytes": task.output_bytes,
                    "mime_type": task.output_mime_type,
                    "width": task.output_width,
                    "height": task.output_height,
                    "frame_count": task.output_frame_count,
                    "fps": task.output_fps,
                }
                for task in tasks
            ],
            "quality_outcome": "PASS",
            "completed_at": datetime.now(UTC).isoformat(),
        }
        relative, package_digest = self.store.write_package(package_id, payload)
        record = ProductionPackageRecord(
            production_package_id=package_id,
            production_job_id=production_job_id,
            creative_package_id=job.creative_package_id,
            plan_digest=job.plan_digest or self._digest(self.repository.plan_for(production_job_id).model_dump(mode="json")),
            package_digest=package_digest,
            package_relpath=relative,
            manifest=payload,
            quality_outcome="PASS",
            created_at=datetime.now(UTC),
        )
        self.repository.save_package(record)
        self.repository.transition_job(
            production_job_id,
            ProductionJobStatus.PRODUCTION_READY,
            finished=True,
            clear_lease=True,
        )
