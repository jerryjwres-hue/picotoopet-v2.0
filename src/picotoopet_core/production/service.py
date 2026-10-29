"""Mac Core orchestration facade for the closed Windows production executor."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from picotoopet_core.approvals.service import ApprovalService
from picotoopet_core.creative.models import (
    CreativeJobStatus,
    CreativePackageRecord,
    CreativeQualityOutcome,
)
from picotoopet_core.creative.repository import CreativeRepository

from .attempts import reserve_or_bind_attempt
from .compiler import compile_production_plan
from .failures import fail_task_durably
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
    ProductionTaskFailureRequest,
    ProductionTaskRecord,
    ProductionTaskStatus,
)
from .package import build_production_package_payload
from .quality import validate_task_commit
from .repository import ProductionRepository
from .store import ProductionArtifactStore
from .reference_assets import (
    ReferenceAssetIdentityV1, approved_reference_descriptor,
    verify_persisted_reference_approval,
)
from .versioned_plan import (
    ApprovedReferenceAuthorizationV11, ProductionJobCreateV11Request,
    ProductionPlanV11, ProductionTaskPlanV11, VersionedProductionPlan,
)


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
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
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
        job = self.repository.create_job(
            production_job_id=production_job_id,
            creative_package_id=package.creative_package_id,
            creative_package_digest=package.package_digest,
            project_key=creative_job.project_key,
            production_profile=request.production_profile,
            idempotency_key=request.idempotency_key,
        )

        # A bound immutable plan belongs to the job version that created it.
        # Replays after a software/compiler upgrade must verify source identity
        # through create_job() above, then reuse that durable plan instead of
        # recompiling it under newer planning semantics.
        if job.plan_digest is not None:
            return job

        plan = compile_production_plan(job.production_job_id, package.manifest, package.package_digest)
        plan_digest = self._digest(plan.model_dump(mode="json"))
        self.repository.save_plan(job.production_job_id, plan, plan_digest)
        return self.repository.get_job(job.production_job_id)

    def create_job_v11(self, request: ProductionJobCreateV11Request) -> ProductionJobRecord:
        """New opt-in job only. Never upgrade any frozen v1.0 job/plan.

        The Windows-reported SHA is an exact consent claim here, not proof that
        Mac saw those bytes. A future authenticated Windows adapter must verify
        them before new GPU POST; v1.1 claim stays disabled until then.
        """
        from .compiler import _task_id  # deterministic Core-owned shot identity
        from .profile import I2V_WORKFLOW_ID

        package = self._creative_package_by_id(request.creative_package_id)
        creative_job = self.creative_repository.get_job(package.creative_job_id)
        if (
            package.quality_outcome is not CreativeQualityOutcome.PASS
            or creative_job.status is not CreativeJobStatus.CREATIVE_READY
        ):
            raise ValueError("PRODUCTION_CREATIVE_PACKAGE_NOT_ELIGIBLE")
        source = self.repository.database.fetchone(
            "SELECT goal_id FROM creative_goal_source_sets WHERE creative_job_id=?",
            (package.creative_job_id,),
        )
        if source is None or creative_job.project_key != f"goal-{source['goal_id']}":
            raise ValueError("PRODUCTION_V11_GOAL_LINEAGE_INVALID")

        # Select only actual persisted approval rows. The request does not
        # provide an asset, file path or user consent boolean.
        source_by_shot: dict[str, tuple[dict[str, object], object]] = {}
        for approval_id in request.approved_reference_ids:
            row = self.repository.database.fetchone(
                "SELECT * FROM approvals WHERE approval_id=?", (approval_id,),
            )
            if (
                row is None or row["approval_type"] != "production.reference_asset.v1"
                or row["status"] != "Approved" or row["task_id"] is not None
                or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC)
            ):
                raise ValueError("PRODUCTION_V11_REFERENCE_NOT_APPROVED")
            scope = json.loads(row["scope_json"])
            if (
                scope.get("schema_version") != "reference_consent_batch.v1"
                or scope.get("creative_package_id") != package.creative_package_id
                or scope.get("creative_package_digest") != package.package_digest
                or scope.get("creative_job_id") != creative_job.creative_job_id
                or scope.get("goal_id") != source["goal_id"]
                or scope.get("rights_scope") != "wan22.i2v.production.v1"
                or scope.get("explicit_rights_attestation") is not True
                or scope.get("byte_provenance") != "WINDOWS_CLIENT_CLAIM_NOT_CORE_HASHED"
            ):
                raise ValueError("PRODUCTION_V11_REFERENCE_SOURCE_MISMATCH")
            for entry in scope.get("references", []):
                shot_id = entry.get("shot_id") if isinstance(entry, dict) else None
                if not isinstance(shot_id, str) or shot_id in source_by_shot:
                    raise ValueError("PRODUCTION_V11_DUPLICATE_SHOT_GRANT")
                source_by_shot[shot_id] = (entry, row)

        existing = self.repository.database.fetchone(
            "SELECT production_job_id FROM production_jobs WHERE idempotency_key=?",
            (request.idempotency_key,),
        )
        job_id = existing["production_job_id"] if existing is not None else str(uuid4())
        if existing is not None:
            old = self.repository.get_job(job_id)
            if old.plan_digest is not None:
                persisted = self.repository.plan_for(job_id)
                if not isinstance(persisted, ProductionPlanV11) or (
                    {t.reference_asset.approval_id for t in persisted.tasks
                     if t.reference_asset is not None}
                    != set(request.approved_reference_ids)
                ):
                    raise ValueError("PRODUCTION_V11_IDEMPOTENCY_CONFLICT")
                if old.creative_package_id != package.creative_package_id:
                    raise ValueError("PRODUCTION_V11_IDEMPOTENCY_CONFLICT")
                return old

        # Never trust legacy Creative manifest paths for v1.1: only approved
        # per-shot managed refs can drive I2V workflow selection.
        sanitized_manifest = dict(package.manifest)
        sanitized_manifest["trusted_local_assets"] = {
            shot: entry["input_relative_path"]
            for shot, (entry, _) in source_by_shot.items()
        }
        base_plan = compile_production_plan(job_id, sanitized_manifest, package.package_digest)
        required = {task.shot_id for task in base_plan.tasks
                    if task.render_intent == "IMAGE_TO_VIDEO"}
        if not required or required != set(source_by_shot):
            raise ValueError("PRODUCTION_V11_REFERENCE_SHOT_COVERAGE_INVALID")

        tasks = []
        for task in base_plan.tasks:
            ref = None
            if task.shot_id in source_by_shot:
                entry, row = source_by_shot[task.shot_id]
                if task.workflow_id != I2V_WORKFLOW_ID or task.execution_disposition.value != "Executable":
                    raise ValueError("PRODUCTION_V11_REFERENCE_SHOT_NOT_EXECUTABLE")
                ref = ReferenceAssetIdentityV1(
                    schema_version="reference_asset.v1",
                    asset_id=entry["asset_id"], goal_id=source["goal_id"],
                    creative_job_id=package.creative_job_id,
                    creative_package_id=package.creative_package_id,
                    production_job_id=job_id, production_task_id=_task_id(job_id, task.shot_id),
                    shot_id=task.shot_id, creative_package_digest=package.package_digest,
                    input_relative_path=entry["input_relative_path"],
                    sha256=entry["sha256"], bytes=entry["bytes"],
                    source_reference=entry["source_reference"],
                    source_digest=entry["source_digest"],
                    rights_scope="wan22.i2v.production.v1",
                    approval_id=row["approval_id"],
                    approval_request_digest=ApprovalService._request_digest(row),
                )
                verify_persisted_reference_approval(self.repository.database, ref)
            tasks.append(ProductionTaskPlanV11.model_validate(
                {**task.model_dump(mode="json"),
                 "reference_asset": None if ref is None else ref.model_dump(mode="json")}
            ))
        plan = ProductionPlanV11.model_validate({
            **base_plan.model_dump(mode="json"),
            "schema_version": "1.1",
            "tasks": [task.model_dump(mode="json") for task in tasks],
        })
        # Retain the *same* v1.0 repository table and immutable canonical digest.
        self.repository.create_job(
            production_job_id=job_id,
            creative_package_id=package.creative_package_id,
            creative_package_digest=package.package_digest,
            project_key=creative_job.project_key,
            production_profile=request.production_profile,
            idempotency_key=request.idempotency_key,
        )
        self.repository.save_plan(job_id, plan, self._digest(plan.model_dump(mode="json")))
        return self.repository.get_job(job_id)

    def authorize_reference_v11(
        self, production_job_id: str, production_task_id: str
    ) -> ApprovedReferenceAuthorizationV11:
        """Fresh Core authority recheck for one already-frozen v1.1 task.

        It does not assert Windows file bytes have been checked. A Windows
        adapter must re-read this near POST and use the Codex byte verifier.
        """
        plan = self.repository.plan_for(production_job_id)
        if not isinstance(plan, ProductionPlanV11):
            raise ValueError("PRODUCTION_V11_REFERENCE_PLAN_REQUIRED")
        job = self.repository.get_job(production_job_id)
        if job.plan_digest != self._digest(plan.model_dump(mode="json")):
            raise ValueError("PRODUCTION_V11_PLAN_DIGEST_MISMATCH")
        task = next(
            (item for item in plan.tasks if item.production_task_id == production_task_id),
            None,
        )
        if task is None or task.reference_asset is None:
            raise ValueError("PRODUCTION_V11_REFERENCE_TASK_NOT_FOUND")
        stored = self.repository.get_task(production_job_id, production_task_id)
        if stored.task_plan.model_dump(mode="json") != task.model_dump(mode="json"):
            raise ValueError("PRODUCTION_V11_TASK_SNAPSHOT_MISMATCH")
        ref = task.reference_asset
        verify_persisted_reference_approval(self.repository.database, ref)
        descriptor = approved_reference_descriptor(self.repository.database, ref)
        return ApprovedReferenceAuthorizationV11(
            production_job_id=production_job_id,
            production_task_id=production_task_id,
            plan_digest=job.plan_digest,
            descriptor=descriptor,
            reference_asset=ref,
        )

    def get_job(self, production_job_id: str) -> ProductionJobRecord:
        return self.repository.get_job(production_job_id)

    def list_jobs(self, *, limit: int = 100) -> list[ProductionJobRecord]:
        return self.repository.list_jobs(limit=limit)

    def get_plan(self, production_job_id: str) -> VersionedProductionPlan:
        return self.repository.plan_for(production_job_id)

    def claim(self, production_job_id: str, executor_id: str) -> ProductionClaimRecord:
        # ── Claim returns full durable snapshots plus an unfinished-only plan ─
        # Validate bound prompt recovery inside the SAME database transaction as
        # lease rotation. Previously a separate read before claim_job allowed an
        # intervening writer to change an authorized prompt into an unknown POST.
        # Any failure rolls back and leaves the previous lease untouched.
        plan = self.repository.plan_for(production_job_id)
        if isinstance(plan, ProductionPlanV11):
            # No GPU lease until exact Core approval + Codex Windows byte
            # verifier and crash-durable Comfy snapshot are connected.
            raise ValueError("PRODUCTION_V11_WORKER_ADAPTER_REQUIRED")

        def authorize_recovery(connection) -> None:  # type: ignore[no-untyped-def]
            rows = connection.execute(
                "SELECT * FROM production_tasks WHERE production_job_id=?",
                (production_job_id,),
            ).fetchall()
            snapshots = {
                row["production_task_id"]: self.repository._task(row)  # noqa: SLF001
                for row in rows
            }
            for planned in plan.tasks:
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
                if snapshot.status is ProductionTaskStatus.RUNNING:
                    bound = connection.execute(
                        "SELECT comfy_prompt_id,status FROM production_attempts "
                        "WHERE production_task_id=? AND attempt_number=?",
                        (snapshot.production_task_id, snapshot.attempt_count),
                    ).fetchone()
                    if bound is None or bound["status"] != "Running":
                        raise ValueError("PRODUCTION_PROMPT_RECOVERY_UNVERIFIED")
                    if snapshot.comfy_prompt_id:
                        # Existing bound attempt: recover this exact prompt only,
                        # never create an additional POST just because history is gone.
                        if bound["comfy_prompt_id"] != snapshot.comfy_prompt_id:
                            raise ValueError("PRODUCTION_PROMPT_RECOVERY_UNVERIFIED")
                    else:
                        # Crash after explicit attempt2 reservation but BEFORE POST:
                        # permit reclaim of the unbound reservation only when
                        # attempt1 is durably recorded as the specific local retry.
                        # Windows RetryPrepared Journal is still required to post.
                        if snapshot.attempt_count != 2 or bound["comfy_prompt_id"] is not None:
                            raise ValueError("PRODUCTION_PROMPT_RECOVERY_UNVERIFIED")
                        prior = connection.execute(
                            "SELECT status,failure_code FROM production_attempts "
                            "WHERE production_task_id=? AND attempt_number=1",
                            (snapshot.production_task_id,),
                        ).fetchone()
                        if (prior is None or prior["status"] != "Failed"
                            or prior["failure_code"] != "COMFY_RETRYABLE_LOCAL_FAILURE"):
                            raise ValueError("PRODUCTION_PROMPT_RECOVERY_UNVERIFIED")
                    # Never exceed the existing bounded attempt budget.
                    if snapshot.attempt_count < 1:
                        raise ValueError("PRODUCTION_PROMPT_RECOVERY_UNVERIFIED")
                    if snapshot.attempt_count > self.repository.MAX_ATTEMPTS_PER_TASK:
                        raise ValueError("PRODUCTION_ATTEMPT_BUDGET_EXHAUSTED")
                elif snapshot.attempt_count >= self.repository.MAX_ATTEMPTS_PER_TASK:
                    raise ValueError("PRODUCTION_ATTEMPT_BUDGET_EXHAUSTED")

        claim = self.repository.claim_job(
            production_job_id, executor_id, before_lease=authorize_recovery
        )
        snapshots = {task.production_task_id: task for task in claim.tasks}
        resume_tasks = []
        for planned in claim.plan.tasks:
            snapshot = snapshots.get(planned.production_task_id)
            if snapshot is None:
                raise ValueError("PRODUCTION_TASK_SNAPSHOT_MISSING")
            if snapshot.status is ProductionTaskStatus.SUCCEEDED:
                continue
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
        # ── Reserve before GPU submit; later prompt binding reuses the same attempt ─
        return reserve_or_bind_attempt(
            self.repository,
            production_job_id=production_job_id,
            production_task_id=production_task_id,
            executor_id=request.executor_id,
            lease_token=request.lease_token,
            comfy_prompt_id=request.comfy_prompt_id,
        )

    def fail_task(
        self,
        production_job_id: str,
        production_task_id: str,
        request: ProductionTaskFailureRequest,
    ) -> ProductionTaskRecord:
        # ── System render failure is durable and distinct from user cancel ───
        return fail_task_durably(
            self.repository,
            production_job_id=production_job_id,
            production_task_id=production_task_id,
            request=request,
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

        # ── Capture lease/source/plan facts before the final transition clears lease ──
        source_package = self._creative_package_by_id(job.creative_package_id)
        plan = self.repository.plan_for(production_job_id)
        self.repository.transition_job(production_job_id, ProductionJobStatus.QUALITY_CHECK)

        package_id = str(uuid4())
        completed_at = datetime.now(UTC)
        payload = build_production_package_payload(
            production_package_id=package_id,
            job=job,
            source_package=source_package,
            plan=plan,
            tasks=tasks,
            completed_at=completed_at,
        )
        relative, package_digest = self.store.write_package(package_id, payload)
        record = ProductionPackageRecord(
            production_package_id=package_id,
            production_job_id=production_job_id,
            creative_package_id=job.creative_package_id,
            plan_digest=job.plan_digest or self._digest(plan.model_dump(mode="json")),
            package_digest=package_digest,
            package_relpath=relative,
            manifest=payload,
            quality_outcome="PASS",
            created_at=completed_at,
        )
        self.repository.save_package(record)
        self.repository.transition_job(
            production_job_id,
            ProductionJobStatus.PRODUCTION_READY,
            finished=True,
            clear_lease=True,
        )
