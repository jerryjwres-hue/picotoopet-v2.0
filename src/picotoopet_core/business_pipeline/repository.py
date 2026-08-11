"""Durable repository for end-to-end business pipeline runs."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from picotoopet_core.db.database import Database

from .models import (
    BusinessAdapterProfile,
    BusinessPipelineQualityOutcome,
    BusinessPipelineRunRecord,
    BusinessPipelineStatus,
    BusinessReturnPackageRecord,
)

_CHILD_FIELDS = {
    "result_package_id",
    "creative_job_id",
    "creative_package_id",
    "production_job_id",
    "production_package_id",
    "return_package_id",
}


class BusinessPipelineRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _run_from_row(row) -> BusinessPipelineRunRecord:  # type: ignore[no-untyped-def]
        return BusinessPipelineRunRecord(
            pipeline_run_id=row["pipeline_run_id"],
            work_package_id=row["work_package_id"],
            result_package_id=row["result_package_id"],
            creative_job_id=row["creative_job_id"],
            creative_package_id=row["creative_package_id"],
            production_job_id=row["production_job_id"],
            production_package_id=row["production_package_id"],
            return_package_id=row["return_package_id"],
            project_key=row["project_key"],
            producer_id=row["producer_id"],
            producer_version=row["producer_version"],
            adapter_profile=BusinessAdapterProfile(row["adapter_profile"]),
            status=BusinessPipelineStatus(row["status"]),
            quality_outcome=(
                BusinessPipelineQualityOutcome(row["quality_outcome"])
                if row["quality_outcome"] is not None
                else None
            ),
            failure_code=row["failure_code"],
            error_message=row["error_message"],
            idempotency_key=row["idempotency_key"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            finished_at=(datetime.fromisoformat(row["finished_at"]) if row["finished_at"] else None),
        )

    @staticmethod
    def _package_from_row(row) -> BusinessReturnPackageRecord:  # type: ignore[no-untyped-def]
        return BusinessReturnPackageRecord(
            return_package_id=row["return_package_id"],
            pipeline_run_id=row["pipeline_run_id"],
            package_digest=row["package_digest"],
            package_relpath=row["package_relpath"],
            manifest=json.loads(row["manifest_json"]),
            quality_outcome=row["quality_outcome"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def create_run(
        self,
        *,
        pipeline_run_id: str,
        work_package_id: str,
        project_key: str,
        producer_id: str,
        producer_version: str,
        adapter_profile: BusinessAdapterProfile,
        idempotency_key: str,
    ) -> BusinessPipelineRunRecord:
        existing_key = self.database.fetchone(
            "SELECT * FROM business_pipeline_runs WHERE idempotency_key=?",
            (idempotency_key,),
        )
        if existing_key is not None:
            return self._run_from_row(existing_key)
        existing_package = self.database.fetchone(
            "SELECT * FROM business_pipeline_runs WHERE work_package_id=?",
            (work_package_id,),
        )
        if existing_package is not None:
            raise ValueError("PIPELINE_WORK_PACKAGE_ALREADY_BOUND")
        timestamp = self._now()
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO business_pipeline_runs("
                "pipeline_run_id,work_package_id,project_key,producer_id,producer_version,adapter_profile,"
                "status,idempotency_key,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    pipeline_run_id,
                    work_package_id,
                    project_key,
                    producer_id,
                    producer_version,
                    adapter_profile.value,
                    BusinessPipelineStatus.READY.value,
                    idempotency_key,
                    timestamp,
                    timestamp,
                ),
            )
        return self.get_run(pipeline_run_id)

    def get_run(self, pipeline_run_id: str) -> BusinessPipelineRunRecord:
        row = self.database.fetchone(
            "SELECT * FROM business_pipeline_runs WHERE pipeline_run_id=?",
            (pipeline_run_id,),
        )
        if row is None:
            raise KeyError(pipeline_run_id)
        return self._run_from_row(row)

    def list_runs(self, *, limit: int = 100) -> list[BusinessPipelineRunRecord]:
        rows = self.database.fetchall(
            "SELECT * FROM business_pipeline_runs ORDER BY created_at DESC LIMIT ?",
            (min(max(limit, 1), 500),),
        )
        return [self._run_from_row(row) for row in rows]

    def bind_child_once(
        self,
        pipeline_run_id: str,
        field: str,
        value: str,
    ) -> BusinessPipelineRunRecord:
        if field not in _CHILD_FIELDS:
            raise ValueError("PIPELINE_CHILD_FIELD_NOT_ALLOWED")
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM business_pipeline_runs WHERE pipeline_run_id=?",
                (pipeline_run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(pipeline_run_id)
            current = row[field]
            if current is not None and current != value:
                raise ValueError("PIPELINE_CHILD_ID_IMMUTABLE")
            if current is None:
                connection.execute(
                    f"UPDATE business_pipeline_runs SET {field}=?,updated_at=? WHERE pipeline_run_id=?",
                    (value, self._now(), pipeline_run_id),
                )
        return self.get_run(pipeline_run_id)

    def transition(
        self,
        pipeline_run_id: str,
        status: BusinessPipelineStatus,
        *,
        quality_outcome: BusinessPipelineQualityOutcome | None = None,
        failure_code: str | None = None,
        error_message: str | None = None,
        finished: bool = False,
    ) -> BusinessPipelineRunRecord:
        timestamp = self._now()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE business_pipeline_runs SET status=?,quality_outcome=?,failure_code=?,error_message=?,"
                "updated_at=?,finished_at=? WHERE pipeline_run_id=?",
                (
                    status.value,
                    quality_outcome.value if quality_outcome is not None else None,
                    failure_code,
                    error_message,
                    timestamp,
                    timestamp if finished else None,
                    pipeline_run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(pipeline_run_id)
        return self.get_run(pipeline_run_id)

    def save_return_package(self, record: BusinessReturnPackageRecord) -> BusinessReturnPackageRecord:
        existing = self.database.fetchone(
            "SELECT * FROM business_return_packages WHERE pipeline_run_id=?",
            (record.pipeline_run_id,),
        )
        if existing is not None:
            existing_record = self._package_from_row(existing)
            if existing_record.return_package_id != record.return_package_id:
                raise ValueError("PIPELINE_RETURN_PACKAGE_IMMUTABLE")
            return existing_record
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO business_return_packages("
                "return_package_id,pipeline_run_id,package_digest,package_relpath,manifest_json,quality_outcome,created_at"
                ") VALUES (?,?,?,?,?,?,?)",
                (
                    record.return_package_id,
                    record.pipeline_run_id,
                    record.package_digest,
                    record.package_relpath,
                    json.dumps(record.manifest, ensure_ascii=False, sort_keys=True),
                    record.quality_outcome,
                    record.created_at.isoformat(),
                ),
            )
        return record

    def return_package_for(self, pipeline_run_id: str) -> BusinessReturnPackageRecord | None:
        row = self.database.fetchone(
            "SELECT * FROM business_return_packages WHERE pipeline_run_id=?",
            (pipeline_run_id,),
        )
        return None if row is None else self._package_from_row(row)
