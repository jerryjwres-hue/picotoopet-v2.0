"""SQLite repository for durable Creative Intelligence facts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from picotoopet_core.db.database import Database

from .models import (
    CreativeDeepAiHandoffRecord,
    CreativeJobRecord,
    CreativeJobStatus,
    CreativePackageRecord,
    CreativeProfile,
    CreativeQualityOutcome,
    CreativeStageKind,
    CreativeStageRunRecord,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CreativeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_job(
        self,
        *,
        creative_job_id: str,
        project_key: str,
        creative_profile: CreativeProfile | str,
        creative_objective: str | None,
        objective_digest: str,
        source_set_digest: str,
        idempotency_key: str,
    ) -> CreativeJobRecord:
        existing = self.database.fetchone(
            "SELECT * FROM creative_jobs WHERE idempotency_key=?",
            (idempotency_key,),
        )
        if existing is not None:
            record = self._job(existing)
            if (
                record.source_set_digest != source_set_digest
                or record.objective_digest != objective_digest
                or record.creative_profile != CreativeProfile(creative_profile)
            ):
                raise ValueError("creative idempotency key conflict")
            return record
        now = _now()
        self.database.execute(
            "INSERT INTO creative_jobs("
            "creative_job_id,project_key,creative_profile,creative_objective,objective_digest,source_set_digest,"
            "status,idempotency_key,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                creative_job_id,
                project_key,
                CreativeProfile(creative_profile).value,
                creative_objective,
                objective_digest,
                source_set_digest,
                CreativeJobStatus.READY.value,
                idempotency_key,
                now,
                now,
            ),
        )
        return self.get_job(creative_job_id)

    def get_job(self, creative_job_id: str) -> CreativeJobRecord:
        row = self.database.fetchone(
            "SELECT * FROM creative_jobs WHERE creative_job_id=?",
            (creative_job_id,),
        )
        if row is None:
            raise KeyError(creative_job_id)
        return self._job(row)

    def list_jobs(self, *, limit: int = 100) -> list[CreativeJobRecord]:
        rows = self.database.fetchall(
            "SELECT * FROM creative_jobs ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        )
        return [self._job(row) for row in rows]

    def transition_job(
        self,
        creative_job_id: str,
        status: CreativeJobStatus,
        *,
        current_stage: CreativeStageKind | None = None,
        creative_package_id: str | None = None,
        deep_ai_handoff_id: str | None = None,
        failure_code: str | None = None,
        error_message: str | None = None,
        finished: bool = False,
    ) -> CreativeJobRecord:
        current = self.get_job(creative_job_id)
        now = _now()
        self.database.execute(
            "UPDATE creative_jobs SET status=?,current_stage=?,creative_package_id=COALESCE(?,creative_package_id),"
            "deep_ai_handoff_id=COALESCE(?,deep_ai_handoff_id),failure_code=?,error_message=?,updated_at=?,"
            "finished_at=? WHERE creative_job_id=?",
            (
                status.value,
                current_stage.value
                if current_stage
                else current.current_stage.value
                if current.current_stage
                else None,
                creative_package_id,
                deep_ai_handoff_id,
                failure_code,
                error_message,
                now,
                now if finished else current.finished_at.isoformat() if current.finished_at else None,
                creative_job_id,
            ),
        )
        return self.get_job(creative_job_id)

    def create_or_get_stage(
        self,
        *,
        creative_job_id: str,
        stage_kind: CreativeStageKind,
        input_digest: str,
        template_version: str,
    ) -> CreativeStageRunRecord:
        row = self.database.fetchone(
            "SELECT * FROM creative_stage_runs WHERE creative_job_id=? AND stage_kind=?",
            (creative_job_id, stage_kind.value),
        )
        if row is not None:
            record = self._stage(row)
            if record.input_digest != input_digest or record.template_version != template_version:
                raise ValueError("creative stage immutable input conflict")
            return record
        now = _now()
        stage_run_id = str(uuid4())
        self.database.execute(
            "INSERT INTO creative_stage_runs("
            "stage_run_id,creative_job_id,stage_kind,status,input_digest,model_attempts,template_version,created_at,updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?)",
            (
                stage_run_id,
                creative_job_id,
                stage_kind.value,
                "Ready",
                input_digest,
                0,
                template_version,
                now,
                now,
            ),
        )
        stage = self.get_stage(creative_job_id, stage_kind)
        assert stage is not None
        return stage

    def get_stage(
        self,
        creative_job_id: str,
        stage_kind: CreativeStageKind,
    ) -> CreativeStageRunRecord | None:
        row = self.database.fetchone(
            "SELECT * FROM creative_stage_runs WHERE creative_job_id=? AND stage_kind=?",
            (creative_job_id, stage_kind.value),
        )
        return None if row is None else self._stage(row)

    def update_stage(
        self,
        stage_run_id: str,
        *,
        status: str,
        model_attempts: int | None = None,
        result: dict[str, object] | None = None,
        result_digest: str | None = None,
        quality_outcome: CreativeQualityOutcome | None = None,
        failure_code: str | None = None,
        error_message: str | None = None,
        finished: bool = False,
    ) -> CreativeStageRunRecord:
        now = _now()
        self.database.execute(
            "UPDATE creative_stage_runs SET status=?,model_attempts=COALESCE(?,model_attempts),"
            "result_digest=COALESCE(?,result_digest),result_json=COALESCE(?,result_json),"
            "quality_outcome=COALESCE(?,quality_outcome),failure_code=?,error_message=?,updated_at=?,"
            "finished_at=? WHERE stage_run_id=?",
            (
                status,
                model_attempts,
                result_digest,
                json.dumps(result, ensure_ascii=False, sort_keys=True) if result is not None else None,
                quality_outcome.value if quality_outcome else None,
                failure_code,
                error_message,
                now,
                now if finished else None,
                stage_run_id,
            ),
        )
        row = self.database.fetchone(
            "SELECT * FROM creative_stage_runs WHERE stage_run_id=?",
            (stage_run_id,),
        )
        if row is None:
            raise KeyError(stage_run_id)
        return self._stage(row)

    def save_package(self, record: CreativePackageRecord) -> CreativePackageRecord:
        existing = self.package_for(record.creative_job_id)
        if existing is not None:
            if existing.package_digest != record.package_digest:
                raise ValueError("creative package conflict")
            return existing
        self.database.execute(
            "INSERT INTO creative_packages(creative_package_id,creative_job_id,source_set_digest,package_digest,"
            "package_relpath,manifest_json,quality_outcome,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                record.creative_package_id,
                record.creative_job_id,
                record.source_set_digest,
                record.package_digest,
                record.package_relpath,
                json.dumps(record.manifest, ensure_ascii=False, sort_keys=True),
                record.quality_outcome.value,
                record.created_at.isoformat(),
            ),
        )
        return record

    def package_for(self, creative_job_id: str) -> CreativePackageRecord | None:
        row = self.database.fetchone(
            "SELECT * FROM creative_packages WHERE creative_job_id=?",
            (creative_job_id,),
        )
        return (
            None
            if row is None
            else CreativePackageRecord(
                creative_package_id=row["creative_package_id"],
                creative_job_id=row["creative_job_id"],
                source_set_digest=row["source_set_digest"],
                package_digest=row["package_digest"],
                package_relpath=row["package_relpath"],
                manifest=json.loads(row["manifest_json"]),
                quality_outcome=row["quality_outcome"],
                created_at=row["created_at"],
            )
        )

    def save_handoff(self, record: CreativeDeepAiHandoffRecord) -> CreativeDeepAiHandoffRecord:
        existing = self.handoff_history_for(record.creative_job_id)
        if existing is not None:
            return existing
        self.database.execute(
            "INSERT INTO creative_deep_ai_handoffs(handoff_id,creative_job_id,stage_kind,source_set_digest,"
            "failed_result_digest,quality_reasons_json,return_schema_json,package_digest,package_relpath,status,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                record.handoff_id,
                record.creative_job_id,
                record.stage_kind.value,
                record.source_set_digest,
                record.failed_result_digest,
                json.dumps(record.quality_reasons, ensure_ascii=False),
                json.dumps(record.return_schema, ensure_ascii=False, sort_keys=True),
                record.package_digest,
                record.package_relpath,
                record.status,
                record.created_at.isoformat(),
            ),
        )
        return record

    def resolve_handoff(self, creative_job_id: str) -> CreativeDeepAiHandoffRecord:
        existing = self.handoff_history_for(creative_job_id)
        if existing is None:
            raise KeyError(creative_job_id)
        if existing.status != "Resolved":
            self.database.execute(
                "UPDATE creative_deep_ai_handoffs SET status='Resolved' WHERE creative_job_id=?",
                (creative_job_id,),
            )
        resolved = self.handoff_history_for(creative_job_id)
        assert resolved is not None
        return resolved

    def handoff_for(self, creative_job_id: str) -> CreativeDeepAiHandoffRecord | None:
        """Return only an active unresolved Handoff so a resolved stage can resume."""

        row = self.database.fetchone(
            "SELECT * FROM creative_deep_ai_handoffs WHERE creative_job_id=? AND status!='Resolved'",
            (creative_job_id,),
        )
        return None if row is None else self._handoff(row)

    def handoff_history_for(self, creative_job_id: str) -> CreativeDeepAiHandoffRecord | None:
        """Return the immutable historical Handoff, including a resolved one, for provenance."""

        row = self.database.fetchone(
            "SELECT * FROM creative_deep_ai_handoffs WHERE creative_job_id=?",
            (creative_job_id,),
        )
        return None if row is None else self._handoff(row)

    @staticmethod
    def _handoff(row) -> CreativeDeepAiHandoffRecord:  # type: ignore[no-untyped-def]
        return CreativeDeepAiHandoffRecord(
            handoff_id=row["handoff_id"],
            creative_job_id=row["creative_job_id"],
            stage_kind=row["stage_kind"],
            source_set_digest=row["source_set_digest"],
            failed_result_digest=row["failed_result_digest"],
            quality_reasons=json.loads(row["quality_reasons_json"]),
            return_schema=json.loads(row["return_schema_json"]),
            package_digest=row["package_digest"],
            package_relpath=row["package_relpath"],
            status=row["status"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _job(row) -> CreativeJobRecord:  # type: ignore[no-untyped-def]
        return CreativeJobRecord(**dict(row))

    @staticmethod
    def _stage(row) -> CreativeStageRunRecord:  # type: ignore[no-untyped-def]
        return CreativeStageRunRecord(
            stage_run_id=row["stage_run_id"],
            creative_job_id=row["creative_job_id"],
            stage_kind=row["stage_kind"],
            status=row["status"],
            input_digest=row["input_digest"],
            result_digest=row["result_digest"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            model_attempts=row["model_attempts"],
            quality_outcome=row["quality_outcome"],
            failure_code=row["failure_code"],
            error_message=row["error_message"],
            template_version=row["template_version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            finished_at=row["finished_at"],
        )
