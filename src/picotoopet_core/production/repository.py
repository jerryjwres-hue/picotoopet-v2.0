"""SQLite repository for durable 2.3.20.1 production facts."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from picotoopet_core.db.database import Database

from .models import (
    ProductionClaimRecord,
    ProductionJobRecord,
    ProductionJobStatus,
    ProductionPackageRecord,
    ProductionPlan,
    ProductionTaskCommitRequest,
    ProductionTaskRecord,
    ProductionTaskStatus,
)


def _now() -> datetime:
    # ── Single UTC clock representation ─────────────────────────────────────
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    # ── SQLite stores canonical ISO timestamps ──────────────────────────────
    return value.astimezone(UTC).isoformat()


def _token_digest(value: str) -> str:
    # ── Raw lease secrets are never persisted ───────────────────────────────
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ProductionRepository:
    MAX_ATTEMPTS_PER_TASK = 2

    def __init__(self, database: Database) -> None:
        self.database = database

    def create_job(
        self,
        *,
        production_job_id: str,
        creative_package_id: str,
        creative_package_digest: str,
        project_key: str,
        production_profile: str,
        idempotency_key: str,
    ) -> ProductionJobRecord:
        # ── Idempotency binds the complete immutable source identity ─────────
        existing = self.database.fetchone(
            "SELECT * FROM production_jobs WHERE idempotency_key=?",
            (idempotency_key,),
        )
        if existing is not None:
            record = self._job(existing)
            if (
                record.creative_package_id != creative_package_id
                or record.creative_package_digest != creative_package_digest
                or record.project_key != project_key
                or record.production_profile.value != production_profile
            ):
                raise ValueError("PRODUCTION_IDEMPOTENCY_CONFLICT")
            return record

        timestamp = _iso(_now())
        self.database.execute(
            "INSERT INTO production_jobs("
            "production_job_id,creative_package_id,creative_package_digest,project_key,production_profile,"
            "status,idempotency_key,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                production_job_id,
                creative_package_id,
                creative_package_digest,
                project_key,
                production_profile,
                ProductionJobStatus.READY.value,
                idempotency_key,
                timestamp,
                timestamp,
            ),
        )
        return self.get_job(production_job_id)

    def get_job(self, production_job_id: str) -> ProductionJobRecord:
        row = self.database.fetchone(
            "SELECT * FROM production_jobs WHERE production_job_id=?",
            (production_job_id,),
        )
        if row is None:
            raise KeyError(production_job_id)
        return self._job(row)

    def list_jobs(self, *, limit: int = 100) -> list[ProductionJobRecord]:
        rows = self.database.fetchall(
            "SELECT * FROM production_jobs ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        )
        return [self._job(row) for row in rows]

    def save_plan(self, production_job_id: str, plan: ProductionPlan, plan_digest: str) -> ProductionPlan:
        # ── Plans are immutable once a digest is bound ──────────────────────
        job = self.get_job(production_job_id)
        if job.plan_digest is not None:
            existing = self.plan_for(production_job_id)
            if job.plan_digest != plan_digest or existing != plan:
                raise ValueError("PRODUCTION_PLAN_CONFLICT")
            return existing

        timestamp = _iso(_now())
        encoded = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        target_status = (
            ProductionJobStatus.NEEDS_HUMAN
            if any(item.execution_disposition.value == "NeedsHuman" for item in plan.tasks)
            else ProductionJobStatus.PLANNED
        )
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE production_jobs SET plan_digest=?,plan_json=?,status=?,updated_at=?,finished_at=? "
                "WHERE production_job_id=? AND plan_digest IS NULL",
                (
                    plan_digest,
                    encoded,
                    target_status.value,
                    timestamp,
                    timestamp if target_status is ProductionJobStatus.NEEDS_HUMAN else None,
                    production_job_id,
                ),
            )
            for task in plan.tasks:
                task_status = (
                    ProductionTaskStatus.NEEDS_HUMAN
                    if task.execution_disposition.value == "NeedsHuman"
                    else ProductionTaskStatus.READY
                )
                connection.execute(
                    "INSERT INTO production_tasks("
                    "production_task_id,production_job_id,shot_id,order_index,render_intent,execution_disposition,"
                    "workflow_id,task_plan_json,status,created_at,updated_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        task.production_task_id,
                        production_job_id,
                        task.shot_id,
                        task.order,
                        task.render_intent,
                        task.execution_disposition.value,
                        task.workflow_id,
                        json.dumps(task.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                        task_status.value,
                        timestamp,
                        timestamp,
                        timestamp if task_status is ProductionTaskStatus.NEEDS_HUMAN else None,
                    ),
                )
        return self.plan_for(production_job_id)

    def plan_for(self, production_job_id: str) -> ProductionPlan:
        row = self.database.fetchone(
            "SELECT plan_json FROM production_jobs WHERE production_job_id=?",
            (production_job_id,),
        )
        if row is None:
            raise KeyError(production_job_id)
        if not row["plan_json"]:
            raise ValueError("PRODUCTION_PLAN_NOT_READY")
        return ProductionPlan.model_validate(json.loads(row["plan_json"]))

    def list_tasks(self, production_job_id: str) -> list[ProductionTaskRecord]:
        rows = self.database.fetchall(
            "SELECT * FROM production_tasks WHERE production_job_id=? ORDER BY order_index",
            (production_job_id,),
        )
        return [self._task(row) for row in rows]

    def get_task(self, production_job_id: str, production_task_id: str) -> ProductionTaskRecord:
        row = self.database.fetchone(
            "SELECT * FROM production_tasks WHERE production_job_id=? AND production_task_id=?",
            (production_job_id, production_task_id),
        )
        if row is None:
            raise KeyError(production_task_id)
        return self._task(row)

    def claim_job(self, production_job_id: str, executor_id: str, lease_seconds: int = 120) -> ProductionClaimRecord:
        # ── One active executor lease per job ────────────────────────────────
        now = _now()
        expires = now + timedelta(seconds=max(30, min(lease_seconds, 600)))
        raw_token = secrets.token_urlsafe(32)
        digest = _token_digest(raw_token)
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM production_jobs WHERE production_job_id=?",
                (production_job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(production_job_id)
            status = ProductionJobStatus(row["status"])
            if status not in {ProductionJobStatus.PLANNED, ProductionJobStatus.CLAIMED, ProductionJobStatus.RENDERING}:
                raise ValueError("PRODUCTION_JOB_NOT_CLAIMABLE")
            lease_expires = datetime.fromisoformat(row["lease_expires_at"]) if row["lease_expires_at"] else None
            if row["lease_token_digest"] and lease_expires and lease_expires > now:
                raise ValueError("PRODUCTION_LEASE_ACTIVE")
            connection.execute(
                "UPDATE production_jobs SET status=?,lease_executor_id=?,lease_token_digest=?,lease_expires_at=?,"
                "updated_at=? WHERE production_job_id=?",
                (
                    ProductionJobStatus.CLAIMED.value,
                    executor_id,
                    digest,
                    _iso(expires),
                    _iso(now),
                    production_job_id,
                ),
            )
        return ProductionClaimRecord(
            production_job_id=production_job_id,
            executor_id=executor_id,
            lease_token=raw_token,
            lease_expires_at=expires,
            plan=self.plan_for(production_job_id),
            tasks=self.list_tasks(production_job_id),
        )

    def heartbeat(
        self,
        production_job_id: str,
        executor_id: str,
        lease_token: str,
        lease_seconds: int = 120,
    ) -> ProductionJobRecord:
        # ── Heartbeats extend only the currently valid lease ────────────────
        self._require_lease(production_job_id, executor_id, lease_token)
        now = _now()
        expires = now + timedelta(seconds=max(30, min(lease_seconds, 600)))
        self.database.execute(
            "UPDATE production_jobs SET lease_expires_at=?,updated_at=? WHERE production_job_id=?",
            (_iso(expires), _iso(now), production_job_id),
        )
        return self.get_job(production_job_id)

    def mark_task_attempt(
        self,
        production_job_id: str,
        production_task_id: str,
        executor_id: str,
        lease_token: str,
        comfy_prompt_id: str | None,
    ) -> ProductionTaskRecord:
        # ── Attempt budget is fixed at initial + one retry ──────────────────
        self._require_lease(production_job_id, executor_id, lease_token)
        task = self.get_task(production_job_id, production_task_id)
        if task.status is ProductionTaskStatus.SUCCEEDED:
            return task
        if task.execution_disposition.value != "Executable":
            raise ValueError("PRODUCTION_TASK_NOT_EXECUTABLE")
        if task.attempt_count >= self.MAX_ATTEMPTS_PER_TASK:
            raise ValueError("PRODUCTION_ATTEMPT_BUDGET_EXHAUSTED")

        attempt_number = task.attempt_count + 1
        timestamp = _iso(_now())
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO production_attempts("
                "production_attempt_id,production_job_id,production_task_id,attempt_number,executor_id,"
                "comfy_prompt_id,status,started_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    production_job_id,
                    production_task_id,
                    attempt_number,
                    executor_id,
                    comfy_prompt_id,
                    "Running",
                    timestamp,
                ),
            )
            connection.execute(
                "UPDATE production_tasks SET attempt_count=?,comfy_prompt_id=?,status=?,updated_at=? "
                "WHERE production_task_id=?",
                (
                    attempt_number,
                    comfy_prompt_id,
                    ProductionTaskStatus.RUNNING.value,
                    timestamp,
                    production_task_id,
                ),
            )
            connection.execute(
                "UPDATE production_jobs SET status=?,updated_at=? WHERE production_job_id=?",
                (ProductionJobStatus.RENDERING.value, timestamp, production_job_id),
            )
        return self.get_task(production_job_id, production_task_id)

    def commit_task_result(
        self,
        production_job_id: str,
        production_task_id: str,
        request: ProductionTaskCommitRequest,
    ) -> ProductionTaskRecord:
        # ── Successful task evidence is immutable ───────────────────────────
        self._require_lease(production_job_id, request.executor_id, request.lease_token)
        current = self.get_task(production_job_id, production_task_id)
        if current.status is ProductionTaskStatus.SUCCEEDED:
            if (
                current.output_sha256 == request.output_sha256
                and current.output_relpath == request.output_relpath
                and current.output_bytes == request.output_bytes
                and current.comfy_prompt_id == request.comfy_prompt_id
            ):
                return current
            raise ValueError("PRODUCTION_TASK_RESULT_CONFLICT")
        if current.attempt_count < 1:
            raise ValueError("PRODUCTION_ATTEMPT_REQUIRED")

        timestamp = _iso(_now())
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE production_tasks SET status=?,comfy_prompt_id=?,output_relpath=?,output_sha256=?,"
                "output_bytes=?,output_mime_type=?,output_width=?,output_height=?,output_frame_count=?,output_fps=?,"
                "updated_at=?,finished_at=? WHERE production_task_id=?",
                (
                    ProductionTaskStatus.SUCCEEDED.value,
                    request.comfy_prompt_id,
                    request.output_relpath,
                    request.output_sha256,
                    request.output_bytes,
                    request.mime_type,
                    request.width,
                    request.height,
                    request.frame_count,
                    request.fps,
                    timestamp,
                    timestamp,
                    production_task_id,
                ),
            )
            connection.execute(
                "UPDATE production_attempts SET status='Succeeded',finished_at=? "
                "WHERE production_task_id=? AND attempt_number=?",
                (timestamp, production_task_id, current.attempt_count),
            )
        return self.get_task(production_job_id, production_task_id)

    def transition_job(
        self,
        production_job_id: str,
        status: ProductionJobStatus,
        *,
        failure_code: str | None = None,
        error_message: str | None = None,
        finished: bool = False,
        clear_lease: bool = False,
    ) -> ProductionJobRecord:
        # ── Core is the only authority for terminal production state ────────
        now = _now()
        current = self.get_job(production_job_id)
        self.database.execute(
            "UPDATE production_jobs SET status=?,failure_code=?,error_message=?,updated_at=?,finished_at=?,"
            "lease_executor_id=?,lease_token_digest=?,lease_expires_at=? WHERE production_job_id=?",
            (
                status.value,
                failure_code,
                error_message,
                _iso(now),
                _iso(now) if finished else _iso(current.finished_at) if current.finished_at else None,
                None if clear_lease else current.lease_executor_id,
                None if clear_lease else self._lease_digest_for(production_job_id),
                None if clear_lease else _iso(current.lease_expires_at) if current.lease_expires_at else None,
                production_job_id,
            ),
        )
        return self.get_job(production_job_id)

    def save_package(self, record: ProductionPackageRecord) -> ProductionPackageRecord:
        existing = self.package_for(record.production_job_id)
        if existing is not None:
            if existing.package_digest != record.package_digest:
                raise ValueError("PRODUCTION_PACKAGE_CONFLICT")
            return existing
        self.database.execute(
            "INSERT INTO production_packages("
            "production_package_id,production_job_id,creative_package_id,plan_digest,package_digest,package_relpath,"
            "manifest_json,quality_outcome,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                record.production_package_id,
                record.production_job_id,
                record.creative_package_id,
                record.plan_digest,
                record.package_digest,
                record.package_relpath,
                json.dumps(record.manifest, ensure_ascii=False, sort_keys=True),
                record.quality_outcome,
                record.created_at.isoformat(),
            ),
        )
        return record

    def package_for(self, production_job_id: str) -> ProductionPackageRecord | None:
        row = self.database.fetchone(
            "SELECT * FROM production_packages WHERE production_job_id=?",
            (production_job_id,),
        )
        if row is None:
            return None
        return ProductionPackageRecord(
            production_package_id=row["production_package_id"],
            production_job_id=row["production_job_id"],
            creative_package_id=row["creative_package_id"],
            plan_digest=row["plan_digest"],
            package_digest=row["package_digest"],
            package_relpath=row["package_relpath"],
            manifest=json.loads(row["manifest_json"]),
            quality_outcome=row["quality_outcome"],
            created_at=row["created_at"],
        )

    def _require_lease(self, production_job_id: str, executor_id: str, lease_token: str) -> None:
        row = self.database.fetchone(
            "SELECT lease_executor_id,lease_token_digest,lease_expires_at FROM production_jobs WHERE production_job_id=?",
            (production_job_id,),
        )
        if row is None:
            raise KeyError(production_job_id)
        expires = datetime.fromisoformat(row["lease_expires_at"]) if row["lease_expires_at"] else None
        if (
            row["lease_executor_id"] != executor_id
            or row["lease_token_digest"] != _token_digest(lease_token)
            or expires is None
            or expires <= _now()
        ):
            raise ValueError("PRODUCTION_LEASE_INVALID")

    def _lease_digest_for(self, production_job_id: str) -> str | None:
        row = self.database.fetchone(
            "SELECT lease_token_digest FROM production_jobs WHERE production_job_id=?",
            (production_job_id,),
        )
        return None if row is None else row["lease_token_digest"]

    @staticmethod
    def _job(row) -> ProductionJobRecord:  # type: ignore[no-untyped-def]
        return ProductionJobRecord(
            production_job_id=row["production_job_id"],
            creative_package_id=row["creative_package_id"],
            creative_package_digest=row["creative_package_digest"],
            project_key=row["project_key"],
            production_profile=row["production_profile"],
            plan_digest=row["plan_digest"],
            status=row["status"],
            lease_executor_id=row["lease_executor_id"],
            lease_expires_at=row["lease_expires_at"],
            failure_code=row["failure_code"],
            error_message=row["error_message"],
            idempotency_key=row["idempotency_key"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            finished_at=row["finished_at"],
        )

    @staticmethod
    def _task(row) -> ProductionTaskRecord:  # type: ignore[no-untyped-def]
        return ProductionTaskRecord(
            production_task_id=row["production_task_id"],
            production_job_id=row["production_job_id"],
            shot_id=row["shot_id"],
            order=row["order_index"],
            render_intent=row["render_intent"],
            execution_disposition=row["execution_disposition"],
            workflow_id=row["workflow_id"],
            task_plan=json.loads(row["task_plan_json"]),
            status=row["status"],
            attempt_count=row["attempt_count"],
            comfy_prompt_id=row["comfy_prompt_id"],
            output_relpath=row["output_relpath"],
            output_sha256=row["output_sha256"],
            output_bytes=row["output_bytes"],
            output_mime_type=row["output_mime_type"],
            output_width=row["output_width"],
            output_height=row["output_height"],
            output_frame_count=row["output_frame_count"],
            output_fps=row["output_fps"],
            failure_code=row["failure_code"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            finished_at=row["finished_at"],
        )
