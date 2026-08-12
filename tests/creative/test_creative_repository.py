from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from picotoopet_core.creative.models import CreativeJobCreateRequest, CreativeJobStatus
from picotoopet_core.creative.repository import CreativeRepository
from picotoopet_core.db.database import Database


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def test_creative_tables_are_retained_through_current_schema(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        tables = {
            row[0]
            for row in database.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert {
            "creative_jobs",
            "creative_job_sources",
            "creative_source_findings",
            "creative_stage_runs",
            "creative_packages",
            "creative_deep_ai_handoffs",
        } <= tables
        assert database.scalar("SELECT MAX(version) FROM schema_migrations") == 15
    finally:
        database.close()


def test_creative_objective_is_bounded() -> None:
    with pytest.raises(ValidationError):
        CreativeJobCreateRequest(
            source_result_package_ids=[str(uuid4())],
            creative_profile="creative.content_plan.v1",
            creative_objective="x" * 2001,
            idempotency_key="creative-too-large",
        )


def test_repository_persists_ready_job_identity(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = CreativeRepository(database)
        job = repository.create_job(
            creative_job_id=str(uuid4()),
            project_key="pet-dryer-us",
            creative_profile="creative.content_plan.v1",
            creative_objective="Create a short product education concept.",
            objective_digest="a" * 64,
            source_set_digest="b" * 64,
            idempotency_key="creative-ready-job",
        )
        assert job.status is CreativeJobStatus.READY
        assert repository.get_job(job.creative_job_id).source_set_digest == "b" * 64
    finally:
        database.close()
