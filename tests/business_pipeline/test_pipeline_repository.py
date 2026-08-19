from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from picotoopet_core.db.database import Database


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


def _pipeline_module():  # type: ignore[no-untyped-def]
    # ── Keep RED as an assertion failure instead of a collection error ──────
    if importlib.util.find_spec("picotoopet_core.business_pipeline.repository") is None:
        pytest.fail("2.3.21.1 business_pipeline repository is not implemented")
    return importlib.import_module("picotoopet_core.business_pipeline.repository")


def _models_module():  # type: ignore[no-untyped-def]
    if importlib.util.find_spec("picotoopet_core.business_pipeline.models") is None:
        pytest.fail("2.3.21.1 business_pipeline models are not implemented")
    return importlib.import_module("picotoopet_core.business_pipeline.models")


def test_migration_14_creates_pipeline_tables(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        # Schema retention gate      21.1 pipeline facts remain present after schema 21.
        assert database.scalar("SELECT MAX(version) FROM schema_migrations") == 21
        tables = {
            row[0]
            for row in database.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'business_%'"
            )
        }
        assert "business_pipeline_runs" in tables
        assert "business_return_packages" in tables
    finally:
        database.close()


def test_pipeline_create_is_idempotent_and_work_package_unique(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository_type = _pipeline_module().BusinessPipelineRepository
        adapter_profile = _models_module().BusinessAdapterProfile.AMAZON_REVIEWS_EXPORT_V1
        repository = repository_type(database)
        work_package_id = str(uuid4())
        first = repository.create_run(
            pipeline_run_id=str(uuid4()),
            work_package_id=work_package_id,
            project_key="pet-dryer-us",
            producer_id="amazon-research-app",
            producer_version="1.0.0",
            adapter_profile=adapter_profile,
            idempotency_key="amazon:pet-dryer-us:batch-001",
        )
        repeated = repository.create_run(
            pipeline_run_id=str(uuid4()),
            work_package_id=work_package_id,
            project_key="pet-dryer-us",
            producer_id="amazon-research-app",
            producer_version="1.0.0",
            adapter_profile=adapter_profile,
            idempotency_key="amazon:pet-dryer-us:batch-001",
        )
        assert repeated.pipeline_run_id == first.pipeline_run_id

        with pytest.raises(ValueError, match="PIPELINE_WORK_PACKAGE_ALREADY_BOUND"):
            repository.create_run(
                pipeline_run_id=str(uuid4()),
                work_package_id=work_package_id,
                project_key="pet-dryer-us",
                producer_id="amazon-research-app",
                producer_version="1.0.0",
                adapter_profile=adapter_profile,
                idempotency_key="different-key",
            )
    finally:
        database.close()


def test_child_identity_is_write_once(tmp_path: Path) -> None:
    database = _database(tmp_path)
    try:
        repository = _pipeline_module().BusinessPipelineRepository(database)
        adapter_profile = _models_module().BusinessAdapterProfile.INSPIRATION_IDEAS_EXPORT_V1
        run = repository.create_run(
            pipeline_run_id=str(uuid4()),
            work_package_id=str(uuid4()),
            project_key="pet-dryer-us",
            producer_id="inspiration-assistant",
            producer_version="1.0.0",
            adapter_profile=adapter_profile,
            idempotency_key="ideas:pet-dryer-us:batch-001",
        )
        creative_job_id = str(uuid4())
        bound = repository.bind_child_once(run.pipeline_run_id, "creative_job_id", creative_job_id)
        assert bound.creative_job_id == creative_job_id
        assert repository.bind_child_once(run.pipeline_run_id, "creative_job_id", creative_job_id).creative_job_id == creative_job_id

        with pytest.raises(ValueError, match="PIPELINE_CHILD_ID_IMMUTABLE"):
            repository.bind_child_once(run.pipeline_run_id, "creative_job_id", str(uuid4()))
    finally:
        database.close()
