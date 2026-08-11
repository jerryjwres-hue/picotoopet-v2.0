"""SQLite repository for durable Creative Intelligence facts."""

from __future__ import annotations

from datetime import UTC, datetime

from picotoopet_core.db.database import Database

from .models import CreativeJobRecord, CreativeJobStatus, CreativeProfile


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CreativeRepository:
    """Persist bounded creative identities and states; raw business data stays elsewhere."""

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
            "SELECT * FROM creative_jobs WHERE idempotency_key = ?",
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
            "creative_job_id,project_key,creative_profile,creative_objective,objective_digest,"
            "source_set_digest,status,idempotency_key,created_at,updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?)",
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
            "SELECT * FROM creative_jobs WHERE creative_job_id = ?",
            (creative_job_id,),
        )
        if row is None:
            raise KeyError(creative_job_id)
        return self._job(row)

    def list_jobs(self, *, limit: int = 100) -> list[CreativeJobRecord]:
        bounded = max(1, min(limit, 200))
        rows = self.database.fetchall(
            "SELECT * FROM creative_jobs ORDER BY created_at DESC LIMIT ?",
            (bounded,),
        )
        return [self._job(row) for row in rows]

    @staticmethod
    def _job(row) -> CreativeJobRecord:  # type: ignore[no-untyped-def]
        return CreativeJobRecord(**dict(row))
