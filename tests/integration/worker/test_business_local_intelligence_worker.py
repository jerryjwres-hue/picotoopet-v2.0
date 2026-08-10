from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from uuid import uuid4

from picotoopet_core.business.execution import BusinessLocalIntelligenceCoordinator
from picotoopet_core.business.models import BusinessWorkPackageStatus, WorkPackageManifest
from picotoopet_core.business.repository import BusinessRepository
from picotoopet_core.business.service import BusinessAutomationService
from picotoopet_core.business.store import BusinessArtifactStore
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.db.database import Database
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository


class FakeLocalIntelligenceAdapter:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def run(self, profile, context, *, correction=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        if not self.responses:
            raise AssertionError("unexpected model call")
        return self.responses.pop(0)


def _result(profile: str, evidence_id: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "analysis_profile": profile,
        "summary": "Customers repeatedly mention drying time as a decision factor.",
        "findings": [
            {
                "rank": 1,
                "title": "Drying time",
                "insight": "Drying time is repeatedly mentioned in the supplied evidence.",
                "confidence": 0.9,
                "evidence_ids": [evidence_id],
            }
        ],
        "warnings": [],
        "needs_deep_ai": False,
        "needs_human": False,
    }


def _write_review_package(tmp_path: Path) -> tuple[Path, WorkPackageManifest]:
    package_id = str(uuid4())
    reviews = (
        '{"review_id":"r1","rating":2,"text":"Drying takes too long"}\n'
        '{"review_id":"r2","rating":5,"text":"Fast drying is the best part"}\n'
    ).encode("utf-8")
    manifest = WorkPackageManifest.model_validate(
        {
            "schema_version": "1.0",
            "package_id": package_id,
            "idempotency_key": f"review-test-{package_id}",
            "producer_id": "amazon-review-analyzer",
            "producer_version": "1.0.0",
            "created_at": "2026-08-10T12:00:00Z",
            "project_key": "pet-dryer-us",
            "analysis_profile": "reviews.voice_of_customer.v1",
            "objective": "Identify supported product improvement opportunities.",
            "inputs": [
                {
                    "artifact_id": "reviews",
                    "path": "inputs/reviews.jsonl",
                    "media_type": "application/x-ndjson",
                    "sha256": hashlib.sha256(reviews).hexdigest(),
                    "size_bytes": len(reviews),
                    "record_key_field": "review_id",
                }
            ],
        }
    )
    archive_path = tmp_path / "work.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{package_id}/work-package.json",
            json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, sort_keys=True),
        )
        archive.writestr(f"{package_id}/inputs/reviews.jsonl", reviews)
    return archive_path, manifest


def _fixture(tmp_path: Path, responses: list[dict[str, object]]):
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    database = Database(paths.database_file)
    database.open()
    database.apply_migrations()
    repository = BusinessRepository(database)
    store = BusinessArtifactStore(paths)
    queue = DiagnosticQueueRepository(database)
    service = BusinessAutomationService(repository, store, queue)
    archive_path, manifest = _write_review_package(tmp_path)
    payload = archive_path.read_bytes()
    source_digest = hashlib.sha256(payload).hexdigest()
    package, session = service.prepare_upload(
        manifest,
        source_digest=source_digest,
        total_size_bytes=len(payload),
    )
    service.write_chunk(
        session.upload_session_id,
        offset=0,
        expected_sha256=source_digest,
        payload=payload,
    )
    package = service.finalize_upload(session.upload_session_id)
    task = next(item for item in queue.list(limit=10) if item.resource_tag == f"business:{package.work_package_id}")
    adapter = FakeLocalIntelligenceAdapter(responses)
    coordinator = BusinessLocalIntelligenceCoordinator(
        database=database,
        queue=queue,
        repository=repository,
        store=store,
        adapter=adapter,
        configured_model_id="gpt-oss:20b",
    )
    return database, service, repository, coordinator, task, package


def test_business_worker_completes_review_package_with_local_model(tmp_path: Path) -> None:
    # Stable evidence ID is derived from the record_key_field value r1.
    evidence_id = "reviews:key:" + hashlib.sha256(b"r1").hexdigest()[:16]
    database, service, repository, coordinator, task, package = _fixture(
        tmp_path,
        [_result("reviews.voice_of_customer.v1", evidence_id)],
    )
    try:
        outcome = coordinator.handler(task)
        final = service.get_work_package(package.work_package_id)
        result = repository.result_for(package.work_package_id)

        assert outcome.summary["status"] == "Completed"
        assert final.status is BusinessWorkPackageStatus.COMPLETED
        assert result is not None
        assert result.quality_outcome.value == "PASS"
        assert result.configured_model_id == "gpt-oss:20b"
    finally:
        database.close()


def test_second_invalid_model_result_becomes_manual_deep_ai_handoff(tmp_path: Path) -> None:
    database, service, repository, coordinator, task, package = _fixture(
        tmp_path,
        [{"not": "the schema"}, {"still": "invalid"}],
    )
    try:
        outcome = coordinator.handler(task)
        final = service.get_work_package(package.work_package_id)
        handoff = repository.handoff_for(package.work_package_id)

        assert outcome.summary["status"] == "NeedsDeepAI"
        assert final.status is BusinessWorkPackageStatus.NEEDS_DEEP_AI
        assert handoff is not None
        assert handoff.status == "ManualReady"
        assert coordinator.adapter.calls == 2
    finally:
        database.close()
