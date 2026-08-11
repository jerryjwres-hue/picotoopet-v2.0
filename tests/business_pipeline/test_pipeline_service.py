from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from picotoopet_core.business.models import BusinessQualityOutcome, BusinessWorkPackageStatus
from picotoopet_core.business_pipeline.models import BusinessAdapterProfile, BusinessPipelineStatus
from picotoopet_core.business_pipeline.repository import BusinessPipelineRepository
from picotoopet_core.creative.models import CreativeJobStatus
from picotoopet_core.db.database import Database
from picotoopet_core.production.models import ProductionJobStatus


def _service_type():  # type: ignore[no-untyped-def]
    if importlib.util.find_spec("picotoopet_core.business_pipeline.service") is None:
        pytest.fail("2.3.21.1 BusinessPipelineService is not implemented")
    return importlib.import_module("picotoopet_core.business_pipeline.service").BusinessPipelineService


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    return database


class _BusinessFake:
    def __init__(self, *, status: BusinessWorkPackageStatus = BusinessWorkPackageStatus.COMPLETED) -> None:
        self.work = SimpleNamespace(
            work_package_id=str(uuid4()),
            status=status,
            producer_id="amazon-research-app",
            producer_version="1.0.0",
            project_key="pet-dryer-us",
            objective="Find supported customer problems and creative opportunities.",
            result_package_id=None,
            failure_code=None,
            error_message=None,
        )
        self.result = SimpleNamespace(
            result_package_id=str(uuid4()),
            quality_outcome=BusinessQualityOutcome.PASS,
            result_digest="1" * 64,
        )

    def get_work_package(self, work_package_id: str):  # type: ignore[no-untyped-def]
        assert work_package_id == self.work.work_package_id
        return self.work

    def result_for(self, work_package_id: str):  # type: ignore[no-untyped-def]
        assert work_package_id == self.work.work_package_id
        return self.result if self.work.status is BusinessWorkPackageStatus.COMPLETED else None


class _CreativeFake:
    def __init__(self) -> None:
        self.create_calls = 0
        self.job = SimpleNamespace(
            creative_job_id=str(uuid4()),
            status=CreativeJobStatus.CREATIVE_READY,
            creative_package_id=str(uuid4()),
            failure_code=None,
            error_message=None,
        )
        self.package = SimpleNamespace(
            creative_package_id=self.job.creative_package_id,
            package_digest="2" * 64,
        )

    def create_job(self, request):  # type: ignore[no-untyped-def]
        self.create_calls += 1
        assert request.source_result_package_ids
        assert request.creative_profile == "creative.content_plan.v1"
        return self.job

    def get_job(self, creative_job_id: str):  # type: ignore[no-untyped-def]
        assert creative_job_id == self.job.creative_job_id
        return self.job

    def get_package(self, creative_job_id: str):  # type: ignore[no-untyped-def]
        assert creative_job_id == self.job.creative_job_id
        return self.package


class _ProductionFake:
    def __init__(self) -> None:
        self.create_calls = 0
        self.job = SimpleNamespace(
            production_job_id=str(uuid4()),
            status=ProductionJobStatus.READY,
            creative_package_id=None,
            failure_code=None,
            error_message=None,
        )
        self.package = SimpleNamespace(
            production_package_id=str(uuid4()),
            package_digest="3" * 64,
        )

    def create_job(self, request):  # type: ignore[no-untyped-def]
        self.create_calls += 1
        assert request.production_profile == "production.comfyui.v1"
        self.job.creative_package_id = request.creative_package_id
        return self.job

    def get_job(self, production_job_id: str):  # type: ignore[no-untyped-def]
        assert production_job_id == self.job.production_job_id
        return self.job

    def get_package(self, production_job_id: str):  # type: ignore[no-untyped-def]
        assert production_job_id == self.job.production_job_id
        return self.package if self.job.status is ProductionJobStatus.PRODUCTION_READY else None


def _pipeline(tmp_path: Path, business: _BusinessFake, creative: _CreativeFake, production: _ProductionFake):  # type: ignore[no-untyped-def]
    database = _database(tmp_path)
    service = _service_type()(
        repository=BusinessPipelineRepository(database),
        business=business,
        creative=creative,
        production=production,
    )
    run = service.create_run(
        work_package_id=business.work.work_package_id,
        adapter_profile=BusinessAdapterProfile.AMAZON_REVIEWS_EXPORT_V1,
        idempotency_key="pipeline:amazon:batch-001",
    )
    return database, service, run


def test_reconcile_binds_each_child_once_across_restart_like_repeats(tmp_path: Path) -> None:
    business = _BusinessFake()
    creative = _CreativeFake()
    production = _ProductionFake()
    database, service, run = _pipeline(tmp_path, business, creative, production)
    try:
        first = service.reconcile(run.pipeline_run_id)
        second = service.reconcile(run.pipeline_run_id)
        assert first.result_package_id == business.result.result_package_id
        assert second.creative_job_id == creative.job.creative_job_id
        assert second.creative_package_id == creative.package.creative_package_id
        assert second.production_job_id == production.job.production_job_id
        assert second.status is BusinessPipelineStatus.AWAITING_GPU
        assert creative.create_calls == 1
        assert production.create_calls == 1
    finally:
        database.close()


def test_reconcile_observes_existing_production_job_without_recreating_it(tmp_path: Path) -> None:
    business = _BusinessFake()
    creative = _CreativeFake()
    production = _ProductionFake()
    database, service, run = _pipeline(tmp_path, business, creative, production)
    try:
        service.reconcile(run.pipeline_run_id)
        production.job.status = ProductionJobStatus.RENDERING
        rendering = service.reconcile(run.pipeline_run_id)
        assert rendering.status is BusinessPipelineStatus.RENDERING
        assert production.create_calls == 1

        production.job.status = ProductionJobStatus.PRODUCTION_READY
        ready = service.reconcile(run.pipeline_run_id)
        assert ready.production_package_id == production.package.production_package_id
        assert ready.status is BusinessPipelineStatus.QUALITY_CHECK
        assert production.create_calls == 1
    finally:
        database.close()


@pytest.mark.parametrize(
    ("work_status", "expected"),
    [
        (BusinessWorkPackageStatus.NEEDS_DEEP_AI, BusinessPipelineStatus.NEEDS_DEEP_AI),
        (BusinessWorkPackageStatus.NEEDS_HUMAN, BusinessPipelineStatus.NEEDS_HUMAN),
        (BusinessWorkPackageStatus.REJECTED, BusinessPipelineStatus.REJECTED),
        (BusinessWorkPackageStatus.FAILED, BusinessPipelineStatus.FAILED),
        (BusinessWorkPackageStatus.CANCELLED, BusinessPipelineStatus.CANCELLED),
    ],
)
def test_business_terminal_state_propagates_without_creating_children(
    tmp_path: Path,
    work_status: BusinessWorkPackageStatus,
    expected: BusinessPipelineStatus,
) -> None:
    business = _BusinessFake(status=work_status)
    creative = _CreativeFake()
    production = _ProductionFake()
    database, service, run = _pipeline(tmp_path, business, creative, production)
    try:
        final = service.reconcile(run.pipeline_run_id)
        assert final.status is expected
        assert creative.create_calls == 0
        assert production.create_calls == 0
    finally:
        database.close()
