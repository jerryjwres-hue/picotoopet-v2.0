from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from picotoopet_core.business.models import (
    BusinessWorkPackageStatus,
    DeepAiHandoffRecord,
    WorkPackageManifest,
)
from picotoopet_core.business.repository import BusinessRepository
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.creative.repository import CreativeRepository
from picotoopet_core.db.database import Database
from picotoopet_core.deep_ai.policy import DeepAiEscalationPolicy
from picotoopet_core.deep_ai.repository import DeepAiRepository
from picotoopet_core.deep_ai.service import CoreDeepAiSourceResolver, DeepAiEscalationService
from picotoopet_core.deep_ai.store import DeepAiSanitizedPackageStore
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository


def test_completed_source_keeps_readiness_and_feedback_identity_available(tmp_path: Path) -> None:
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    try:
        paths = RuntimePaths.from_root(tmp_path / "runtime")
        paths.ensure()
        business = BusinessRepository(database)
        creative = CreativeRepository(database)
        queue = DiagnosticQueueRepository(database)
        resolver = CoreDeepAiSourceResolver(business, creative)
        service = DeepAiEscalationService(
            repository=DeepAiRepository(database),
            store=DeepAiSanitizedPackageStore(paths),
            approvals=HandoffApprovalService(database, queue),
            source_resolver=resolver,
            policy=DeepAiEscalationPolicy.default(),
        )

        package_id = str(uuid4())
        manifest = WorkPackageManifest.model_validate(
            {
                "schema_version": "1.0",
                "package_id": package_id,
                "idempotency_key": f"terminal-control:{package_id}",
                "producer_id": "amazon-research-app",
                "producer_version": "1.0.0",
                "created_at": "2026-08-11T12:00:00Z",
                "project_key": "pet-dryer-us",
                "analysis_profile": "reviews.voice_of_customer.v1",
                "objective": "Find supported customer insights.",
                "inputs": [
                    {
                        "artifact_id": "reviews",
                        "path": "inputs/reviews.jsonl",
                        "media_type": "application/x-ndjson",
                        "sha256": "a" * 64,
                        "size_bytes": 128,
                        "record_key_field": "review_id",
                    }
                ],
            }
        )
        business.create_or_get_work_package(
            manifest,
            source_digest="b" * 64,
            compressed_size_bytes=256,
        )
        handoff = DeepAiHandoffRecord(
            handoff_id=str(uuid4()),
            work_package_id=package_id,
            source_digest="b" * 64,
            preprocess_digest="c" * 64,
            local_result_digest="d" * 64,
            quality_reasons=["semantic uncertainty"],
            return_schema={"type": "object", "required": ["findings"]},
            package_digest="e" * 64,
            package_relpath=f"runtime/business/handoffs/{package_id}.zip",
            status="Prepared",
        )
        business.save_handoff(handoff)
        business.transition_work_package(
            package_id,
            BusinessWorkPackageStatus.NEEDS_DEEP_AI,
            preprocess_digest="c" * 64,
            deep_ai_handoff_id=handoff.handoff_id,
            finished=True,
        )
        job = service.prepare_from_source(
            source_kind="business.local_intelligence",
            source_id=package_id,
            requested_by="test",
        )

        # PASS continuation changes the source out of NEEDS_DEEP_AI, but the paid-AI
        # audit/control plane must still be readable and accept bounded feedback facts.
        business.transition_work_package(
            package_id,
            BusinessWorkPackageStatus.COMPLETED,
            result_package_id=str(uuid4()),
            finished=True,
        )

        readiness = service.readiness(job.escalation_job_id)
        assert readiness.execution_enabled is False
        assert readiness.manual_handoff_id == handoff.handoff_id
        assert resolver.project_key_for("business.local_intelligence", package_id) == "pet-dryer-us"
    finally:
        database.close()
