from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from picotoopet_core.business.models import BusinessAnalysisProfile, BusinessQualityOutcome, BusinessWorkPackageStatus
from picotoopet_core.business_pipeline.models import BusinessAdapterProfile, BusinessPipelineStatus
from picotoopet_core.business_pipeline.repository import BusinessPipelineRepository
from picotoopet_core.creative.models import CreativeJobStatus
from picotoopet_core.db.database import Database
from picotoopet_core.production.models import ProductionJobStatus


def _service_type():  # type: ignore[no-untyped-def]
    return importlib.import_module("picotoopet_core.business_pipeline.service").BusinessPipelineService


def _store_type():  # type: ignore[no-untyped-def]
    if importlib.util.find_spec("picotoopet_core.business_pipeline.store") is None:
        pytest.fail("2.3.21.1 BusinessReturnPackageStore is not implemented")
    return importlib.import_module("picotoopet_core.business_pipeline.store").BusinessReturnPackageStore


class _CaptureStore:
    def __init__(self) -> None:
        self.payload: dict[str, object] | None = None

    def write_package(self, return_package_id: str, payload: dict[str, object]) -> tuple[str, str]:
        self.payload = payload
        return f"runtime/business/returns/{return_package_id}.zip", "9" * 64


class _Business:
    def __init__(self) -> None:
        self.work = SimpleNamespace(
            work_package_id=str(uuid4()), producer_id="amazon-research-app", producer_version="1.4.0",
            project_key="pet-dryer-us", analysis_profile=BusinessAnalysisProfile.REVIEWS_VOICE_OF_CUSTOMER_V1,
            objective="Find supported customer problems.", status=BusinessWorkPackageStatus.COMPLETED,
            source_digest="1" * 64, result_package_id=None, failure_code=None, error_message=None,
        )
        self.result = SimpleNamespace(
            result_package_id=str(uuid4()), work_package_id=self.work.work_package_id,
            analysis_profile=BusinessAnalysisProfile.REVIEWS_VOICE_OF_CUSTOMER_V1,
            quality_outcome=BusinessQualityOutcome.PASS, result_digest="2" * 64,
            source_digest="1" * 64, preprocess_digest="3" * 64,
            warnings=["source warning retained"],
        )

    def get_work_package(self, work_package_id: str):  # type: ignore[no-untyped-def]
        assert work_package_id == self.work.work_package_id
        return self.work

    def result_for(self, work_package_id: str):  # type: ignore[no-untyped-def]
        assert work_package_id == self.work.work_package_id
        return self.result


class _Creative:
    def __init__(self) -> None:
        self.job = SimpleNamespace(
            creative_job_id=str(uuid4()), status=CreativeJobStatus.CREATIVE_READY, creative_package_id=str(uuid4()),
            failure_code=None, error_message=None,
        )
        self.package = SimpleNamespace(
            creative_package_id=self.job.creative_package_id, creative_job_id=self.job.creative_job_id,
            package_digest="4" * 64, source_set_digest="5" * 64,
            manifest={
                "source_result_packages": [{"result_package_id": "source-result", "result_digest": "6" * 64}],
                "source_findings": [{"source_finding_ref": "source-result:1", "evidence_ids": ["e-1"]}],
            },
        )

    def create_job(self, request):  # type: ignore[no-untyped-def]
        return self.job

    def get_job(self, creative_job_id: str):  # type: ignore[no-untyped-def]
        assert creative_job_id == self.job.creative_job_id
        return self.job

    def get_package(self, creative_job_id: str):  # type: ignore[no-untyped-def]
        assert creative_job_id == self.job.creative_job_id
        return self.package


class _Production:
    def __init__(self, creative_package_id: str) -> None:
        self.job = SimpleNamespace(
            production_job_id=str(uuid4()), creative_package_id=creative_package_id,
            status=ProductionJobStatus.PRODUCTION_READY, failure_code=None, error_message=None,
        )
        self.package = SimpleNamespace(
            production_package_id=str(uuid4()), production_job_id=self.job.production_job_id,
            creative_package_id=creative_package_id, package_digest="7" * 64, plan_digest="8" * 64,
            manifest={
                "quality_outcome": "PASS",
                "outputs": [{
                    "production_task_id": str(uuid4()), "shot_id": "shot-001", "workflow_id": "comfy.wan22.ti2v5b.t2v.v1",
                    "comfy_prompt_id": "prompt-001", "output_relpath": "PicotooPet/production/job/001-shot-001.webm",
                    "output_sha256": "a" * 64, "output_bytes": 8192, "mime_type": "video/webm",
                    "width": 832, "height": 480, "frame_count": 81, "fps": 24,
                }],
                "creative_provenance": {"source_findings": [{"source_finding_ref": "source-result:1", "evidence_ids": ["e-1"]}]},
                "warnings": [], "failures": [],
            },
        )

    def create_job(self, request):  # type: ignore[no-untyped-def]
        self.job.creative_package_id = request.creative_package_id
        return self.job

    def get_job(self, production_job_id: str):  # type: ignore[no-untyped-def]
        assert production_job_id == self.job.production_job_id
        return self.job

    def get_package(self, production_job_id: str):  # type: ignore[no-untyped-def]
        assert production_job_id == self.job.production_job_id
        return self.package


def test_completed_pipeline_writes_one_immutable_return_package(tmp_path: Path) -> None:
    database = Database(tmp_path / "core.db")
    database.open(); database.apply_migrations()
    business = _Business(); creative = _Creative(); production = _Production(creative.package.creative_package_id)
    store = _CaptureStore()
    service = _service_type()(
        repository=BusinessPipelineRepository(database), business=business, creative=creative, production=production,
        return_store=store,
    )
    try:
        run = service.create_run(
            work_package_id=business.work.work_package_id,
            adapter_profile=BusinessAdapterProfile.AMAZON_REVIEWS_EXPORT_V1,
            idempotency_key="pipeline:return-package",
        )
        completed = service.reconcile(run.pipeline_run_id)
        assert completed.status is BusinessPipelineStatus.COMPLETED
        assert completed.return_package_id is not None
        record = service.get_return_package(run.pipeline_run_id)
        assert record is not None and record.package_digest == "9" * 64

        payload = store.payload
        assert payload is not None
        assert payload["schema_version"] == "1.0"
        assert payload["pipeline_run_id"] == run.pipeline_run_id
        assert payload["producer"] == {"producer_id": "amazon-research-app", "producer_version": "1.4.0"}
        assert payload["adapter_profile"] == "amazon.reviews_export.v1"
        assert payload["project_key"] == "pet-dryer-us"
        packages = payload["packages"]
        assert packages["work"]["package_id"] == business.work.work_package_id
        assert packages["work"]["source_digest"] == "1" * 64
        assert packages["result"]["package_id"] == business.result.result_package_id
        assert packages["result"]["result_digest"] == "2" * 64
        assert packages["creative"]["package_id"] == creative.package.creative_package_id
        assert packages["creative"]["package_digest"] == "4" * 64
        assert packages["production"]["package_id"] == production.package.production_package_id
        assert packages["production"]["package_digest"] == "7" * 64
        assert payload["outputs"][0]["output_sha256"] == "a" * 64
        assert payload["provenance"] == production.package.manifest["creative_provenance"]
        assert payload["warnings"] == ["source warning retained"]
        assert payload["failures"] == []
        assert payload["quality_outcome"] == "PASS"

        again = service.reconcile(run.pipeline_run_id)
        assert again.return_package_id == completed.return_package_id
        assert service.get_return_package(run.pipeline_run_id).return_package_id == record.return_package_id
    finally:
        database.close()


def test_managed_return_store_is_core_owned(tmp_path: Path) -> None:
    # ── Store path is derived from RuntimePaths + UUID, never producer input ─
    from picotoopet_core.config.paths import RuntimePaths

    paths = RuntimePaths.from_root(tmp_path / "runtime-root")
    store = _store_type()(paths)
    return_id = str(uuid4())
    relative, digest = store.write_package(return_id, {"schema_version": "1.0", "return_package_id": return_id})
    resolved = store.resolve_managed_relative(relative)
    assert resolved.is_file()
    assert resolved.parent == paths.business_root / "returns"
    assert len(digest) == 64
