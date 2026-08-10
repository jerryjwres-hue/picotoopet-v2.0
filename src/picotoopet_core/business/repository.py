"""SQLite repository for durable business automation facts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from picotoopet_core.db.database import Database

from .models import (
    BusinessAnalysisProfile,
    BusinessQualityOutcome,
    BusinessResultPackageRecord,
    BusinessRunStatus,
    BusinessUploadSessionRecord,
    BusinessWorkPackageStatus,
    DeepAiHandoffRecord,
    LocalIntelligenceRunRecord,
    WorkPackageManifest,
    WorkPackageRecord,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class BusinessRepository:
    """Persist business package/run/result facts without storing raw datasets as BLOBs."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def create_or_get_work_package(
        self,
        manifest: WorkPackageManifest,
        *,
        source_digest: str,
        compressed_size_bytes: int,
    ) -> WorkPackageRecord:
        by_package = self.database.fetchone(
            "SELECT * FROM business_work_packages WHERE work_package_id = ?",
            (manifest.package_id,),
        )
        if by_package is not None:
            record = self._work_package(by_package)
            if record.source_digest != source_digest:
                raise ValueError("package identity digest conflict")
            return record

        by_idempotency = self.database.fetchone(
            "SELECT * FROM business_work_packages WHERE idempotency_key = ?",
            (manifest.idempotency_key,),
        )
        if by_idempotency is not None:
            record = self._work_package(by_idempotency)
            if record.source_digest != source_digest or record.work_package_id != manifest.package_id:
                raise ValueError("idempotency key conflict")
            return record

        now = _now()
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO business_work_packages("
                "work_package_id,idempotency_key,producer_id,producer_version,project_key,"
                "analysis_profile,objective,status,source_digest,compressed_size_bytes,"
                "manifest_json,created_at,updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    manifest.package_id,
                    manifest.idempotency_key,
                    manifest.producer_id,
                    manifest.producer_version,
                    manifest.project_key,
                    manifest.analysis_profile.value,
                    manifest.objective,
                    BusinessWorkPackageStatus.RECEIVING.value,
                    source_digest,
                    compressed_size_bytes,
                    json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            for item in manifest.inputs:
                connection.execute(
                    "INSERT INTO business_artifacts("
                    "artifact_row_id,work_package_id,artifact_id,relative_path,media_type,sha256,"
                    "size_bytes,record_key_field,created_at"
                    ") VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        str(uuid4()),
                        manifest.package_id,
                        item.artifact_id,
                        item.path,
                        item.media_type,
                        item.sha256,
                        item.size_bytes,
                        item.record_key_field,
                        now,
                    ),
                )
        return self.get_work_package(manifest.package_id)

    def get_work_package(self, work_package_id: str) -> WorkPackageRecord:
        row = self.database.fetchone(
            "SELECT * FROM business_work_packages WHERE work_package_id = ?",
            (work_package_id,),
        )
        if row is None:
            raise KeyError(work_package_id)
        return self._work_package(row)

    def list_work_packages(self, *, limit: int = 200) -> list[WorkPackageRecord]:
        rows = self.database.fetchall(
            "SELECT * FROM business_work_packages ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [self._work_package(row) for row in rows]

    def manifest_for(self, work_package_id: str) -> WorkPackageManifest:
        row = self.database.fetchone(
            "SELECT manifest_json FROM business_work_packages WHERE work_package_id = ?",
            (work_package_id,),
        )
        if row is None:
            raise KeyError(work_package_id)
        return WorkPackageManifest.model_validate_json(row["manifest_json"])

    def transition_work_package(
        self,
        work_package_id: str,
        status: BusinessWorkPackageStatus,
        *,
        failure_code: str | None = None,
        error_message: str | None = None,
        finished: bool = False,
        uncompressed_size_bytes: int | None = None,
        package_object_relpath: str | None = None,
        preprocess_digest: str | None = None,
        result_package_id: str | None = None,
        deep_ai_handoff_id: str | None = None,
    ) -> WorkPackageRecord:
        current = self.get_work_package(work_package_id)
        now = _now()
        self.database.execute(
            "UPDATE business_work_packages SET status=?,failure_code=?,error_message=?,updated_at=?,"
            "finished_at=?,uncompressed_size_bytes=COALESCE(?,uncompressed_size_bytes),"
            "package_object_relpath=COALESCE(?,package_object_relpath),"
            "preprocess_digest=COALESCE(?,preprocess_digest),"
            "result_package_id=COALESCE(?,result_package_id),"
            "deep_ai_handoff_id=COALESCE(?,deep_ai_handoff_id) WHERE work_package_id=?",
            (
                status.value,
                failure_code,
                error_message,
                now,
                now if finished else current.finished_at.isoformat() if current.finished_at else None,
                uncompressed_size_bytes,
                package_object_relpath,
                preprocess_digest,
                result_package_id,
                deep_ai_handoff_id,
                work_package_id,
            ),
        )
        return self.get_work_package(work_package_id)

    def create_upload_session(
        self,
        *,
        work_package_id: str,
        source_digest: str,
        total_size_bytes: int,
        chunk_size_bytes: int,
        staging_relpath: str,
    ) -> BusinessUploadSessionRecord:
        existing = self.database.fetchone(
            "SELECT * FROM business_upload_sessions WHERE work_package_id = ?",
            (work_package_id,),
        )
        if existing is not None:
            record = self._upload_session(existing)
            if record.source_digest != source_digest or record.total_size_bytes != total_size_bytes:
                raise ValueError("upload session identity conflict")
            return record
        now = _now()
        upload_session_id = str(uuid4())
        self.database.execute(
            "INSERT INTO business_upload_sessions("
            "upload_session_id,work_package_id,source_digest,total_size_bytes,verified_size_bytes,"
            "chunk_size_bytes,status,staging_relpath,created_at,updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                upload_session_id,
                work_package_id,
                source_digest,
                total_size_bytes,
                0,
                chunk_size_bytes,
                "Receiving",
                staging_relpath,
                now,
                now,
            ),
        )
        return self.get_upload_session(upload_session_id)

    def get_upload_session(self, upload_session_id: str) -> BusinessUploadSessionRecord:
        row = self.database.fetchone(
            "SELECT * FROM business_upload_sessions WHERE upload_session_id = ?",
            (upload_session_id,),
        )
        if row is None:
            raise KeyError(upload_session_id)
        return self._upload_session(row)

    def record_upload_chunk(
        self,
        *,
        upload_session_id: str,
        offset: int,
        size_bytes: int,
        sha256: str,
    ) -> None:
        existing = self.database.fetchone(
            "SELECT size_bytes,sha256 FROM business_upload_chunks WHERE upload_session_id=? AND chunk_offset=?",
            (upload_session_id, offset),
        )
        if existing is not None:
            if int(existing["size_bytes"]) != size_bytes or existing["sha256"] != sha256:
                raise ValueError("upload chunk conflict")
            return
        now = _now()
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO business_upload_chunks(upload_session_id,chunk_offset,size_bytes,sha256,verified_at) "
                "VALUES (?,?,?,?,?)",
                (upload_session_id, offset, size_bytes, sha256, now),
            )
            verified = connection.execute(
                "SELECT COALESCE(SUM(size_bytes),0) FROM business_upload_chunks WHERE upload_session_id=?",
                (upload_session_id,),
            ).fetchone()[0]
            connection.execute(
                "UPDATE business_upload_sessions SET verified_size_bytes=?,updated_at=? WHERE upload_session_id=?",
                (verified, now, upload_session_id),
            )

    def finalize_upload_session(self, upload_session_id: str) -> BusinessUploadSessionRecord:
        now = _now()
        self.database.execute(
            "UPDATE business_upload_sessions SET status='Finalized',updated_at=?,finalized_at=? WHERE upload_session_id=?",
            (now, now, upload_session_id),
        )
        return self.get_upload_session(upload_session_id)

    def create_or_get_run(
        self,
        *,
        work_package_id: str,
        analysis_profile: BusinessAnalysisProfile,
        source_digest: str,
        model_adapter_version: str,
        configured_model_id: str,
        template_version: str,
        idempotency_key: str,
    ) -> LocalIntelligenceRunRecord:
        row = self.database.fetchone(
            "SELECT * FROM local_intelligence_runs WHERE idempotency_key=?",
            (idempotency_key,),
        )
        if row is not None:
            return self._run(row)
        now = _now()
        run_id = str(uuid4())
        self.database.execute(
            "INSERT INTO local_intelligence_runs("
            "run_id,work_package_id,status,analysis_profile,source_digest,model_adapter_version,"
            "configured_model_id,template_version,model_attempts,idempotency_key,created_at,updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                work_package_id,
                BusinessRunStatus.READY.value,
                analysis_profile.value,
                source_digest,
                model_adapter_version,
                configured_model_id,
                template_version,
                0,
                idempotency_key,
                now,
                now,
            ),
        )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> LocalIntelligenceRunRecord:
        row = self.database.fetchone("SELECT * FROM local_intelligence_runs WHERE run_id=?", (run_id,))
        if row is None:
            raise KeyError(run_id)
        return self._run(row)

    def update_run(
        self,
        run_id: str,
        *,
        status: BusinessRunStatus,
        preprocess_digest: str | None = None,
        model_attempts: int | None = None,
        quality_outcome: BusinessQualityOutcome | None = None,
        failure_code: str | None = None,
        error_message: str | None = None,
        finished: bool = False,
    ) -> LocalIntelligenceRunRecord:
        now = _now()
        self.database.execute(
            "UPDATE local_intelligence_runs SET status=?,preprocess_digest=COALESCE(?,preprocess_digest),"
            "model_attempts=COALESCE(?,model_attempts),quality_outcome=COALESCE(?,quality_outcome),"
            "failure_code=?,error_message=?,updated_at=?,finished_at=? WHERE run_id=?",
            (
                status.value,
                preprocess_digest,
                model_attempts,
                quality_outcome.value if quality_outcome else None,
                failure_code,
                error_message,
                now,
                now if finished else None,
                run_id,
            ),
        )
        return self.get_run(run_id)

    def save_result(self, record: BusinessResultPackageRecord) -> BusinessResultPackageRecord:
        existing = self.database.fetchone(
            "SELECT * FROM business_result_packages WHERE work_package_id=?",
            (record.work_package_id,),
        )
        if existing is not None:
            current = self._result(existing)
            if current.result_digest != record.result_digest:
                raise ValueError("result package conflict")
            return current
        self.database.execute(
            "INSERT INTO business_result_packages("
            "result_package_id,work_package_id,analysis_profile,source_digest,preprocess_digest,"
            "model_adapter_version,configured_model_id,template_version,quality_outcome,result_digest,"
            "package_relpath,result_json,warnings_json,created_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record.result_package_id,
                record.work_package_id,
                record.analysis_profile.value,
                record.source_digest,
                record.preprocess_digest,
                record.model_adapter_version,
                record.configured_model_id,
                record.template_version,
                record.quality_outcome.value,
                record.result_digest,
                record.package_relpath,
                json.dumps(record.result, ensure_ascii=False, sort_keys=True),
                json.dumps(record.warnings, ensure_ascii=False),
                record.created_at.isoformat(),
            ),
        )
        return record

    def result_for(self, work_package_id: str) -> BusinessResultPackageRecord | None:
        row = self.database.fetchone(
            "SELECT * FROM business_result_packages WHERE work_package_id=?",
            (work_package_id,),
        )
        return None if row is None else self._result(row)

    def save_handoff(self, record: DeepAiHandoffRecord) -> DeepAiHandoffRecord:
        existing = self.database.fetchone(
            "SELECT * FROM deep_ai_handoffs WHERE work_package_id=?",
            (record.work_package_id,),
        )
        if existing is not None:
            return self._handoff(existing)
        self.database.execute(
            "INSERT INTO deep_ai_handoffs("
            "handoff_id,work_package_id,source_digest,preprocess_digest,local_result_digest,"
            "quality_reasons_json,return_schema_json,package_digest,package_relpath,status,created_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                record.handoff_id,
                record.work_package_id,
                record.source_digest,
                record.preprocess_digest,
                record.local_result_digest,
                json.dumps(record.quality_reasons, ensure_ascii=False),
                json.dumps(record.return_schema, ensure_ascii=False, sort_keys=True),
                record.package_digest,
                record.package_relpath,
                record.status,
                record.created_at.isoformat(),
            ),
        )
        return record

    def handoff_for(self, work_package_id: str) -> DeepAiHandoffRecord | None:
        row = self.database.fetchone(
            "SELECT * FROM deep_ai_handoffs WHERE work_package_id=?",
            (work_package_id,),
        )
        return None if row is None else self._handoff(row)

    @staticmethod
    def _work_package(row) -> WorkPackageRecord:  # type: ignore[no-untyped-def]
        return WorkPackageRecord(
            work_package_id=row["work_package_id"],
            idempotency_key=row["idempotency_key"],
            producer_id=row["producer_id"],
            producer_version=row["producer_version"],
            project_key=row["project_key"],
            analysis_profile=row["analysis_profile"],
            objective=row["objective"],
            status=row["status"],
            source_digest=row["source_digest"],
            compressed_size_bytes=row["compressed_size_bytes"],
            uncompressed_size_bytes=row["uncompressed_size_bytes"],
            package_object_relpath=row["package_object_relpath"],
            preprocess_digest=row["preprocess_digest"],
            result_package_id=row["result_package_id"],
            deep_ai_handoff_id=row["deep_ai_handoff_id"],
            failure_code=row["failure_code"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            finished_at=row["finished_at"],
        )

    @staticmethod
    def _upload_session(row) -> BusinessUploadSessionRecord:  # type: ignore[no-untyped-def]
        return BusinessUploadSessionRecord(**dict(row))

    @staticmethod
    def _run(row) -> LocalIntelligenceRunRecord:  # type: ignore[no-untyped-def]
        return LocalIntelligenceRunRecord(**dict(row))

    @staticmethod
    def _result(row) -> BusinessResultPackageRecord:  # type: ignore[no-untyped-def]
        return BusinessResultPackageRecord(
            result_package_id=row["result_package_id"],
            work_package_id=row["work_package_id"],
            analysis_profile=row["analysis_profile"],
            source_digest=row["source_digest"],
            preprocess_digest=row["preprocess_digest"],
            model_adapter_version=row["model_adapter_version"],
            configured_model_id=row["configured_model_id"],
            template_version=row["template_version"],
            quality_outcome=row["quality_outcome"],
            result_digest=row["result_digest"],
            package_relpath=row["package_relpath"],
            result=json.loads(row["result_json"]),
            warnings=json.loads(row["warnings_json"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _handoff(row) -> DeepAiHandoffRecord:  # type: ignore[no-untyped-def]
        return DeepAiHandoffRecord(
            handoff_id=row["handoff_id"],
            work_package_id=row["work_package_id"],
            source_digest=row["source_digest"],
            preprocess_digest=row["preprocess_digest"],
            local_result_digest=row["local_result_digest"],
            quality_reasons=json.loads(row["quality_reasons_json"]),
            return_schema=json.loads(row["return_schema_json"]),
            package_digest=row["package_digest"],
            package_relpath=row["package_relpath"],
            status=row["status"],
            created_at=row["created_at"],
        )
