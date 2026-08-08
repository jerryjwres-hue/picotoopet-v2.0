from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from picotoopet_core.automation.artifacts import ArtifactProvenanceService
from picotoopet_core.automation.continuation import WorkflowContinuationService
from picotoopet_core.automation.models import (
    ArtifactProvenanceCreate,
    WorkflowContinuationCreate,
    WorkflowCreate,
    WorkflowStepCreate,
)
from picotoopet_core.automation.repository import AutomationRepository
from picotoopet_core.automation.service import WorkflowService
from picotoopet_core.db.database import Database


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "automation-security.db")
    database.open()
    database.apply_migrations()
    return database


def _workflow(service: WorkflowService, key: str = "evidence"):
    return service.create_workflow(
        WorkflowCreate(
            project_id=None,
            name=key,
            priority=100,
            max_concurrency=1,
            idempotency_key=f"{key}-v1",
            steps=[WorkflowStepCreate(step_key="step", task_type="system.noop")],
        )
    )


def test_unregistered_arbitrary_task_type_requires_explicit_capability_contract() -> None:
    """A workflow may not smuggle an arbitrary executable type into the queue."""

    with pytest.raises(ValidationError, match="required_capability"):
        WorkflowStepCreate(step_key="unsafe", task_type="shell.exec")

    allowed_for_routing = WorkflowStepCreate(
        step_key="typed",
        task_type="creative.render",
        required_capability="local.video.generation",
    )
    assert allowed_for_routing.required_capability == "local.video.generation"


def test_artifact_provenance_is_digest_immutable_and_records_input_links(tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository = AutomationRepository(database)
    workflow = _workflow(WorkflowService(database), "provenance")
    now = datetime.now(UTC).isoformat()
    database.execute(
        """
        INSERT INTO projects (
            project_id, title, project_type, source_app, classification,
            workspace_root, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)
        """,
        ("project-evidence", "Evidence", "automation", "test", "INTERNAL", "Active", now, now),
    )
    for artifact_id, digest in (("input-artifact", "1" * 64), ("output-artifact", "2" * 64)):
        database.execute(
            """
            INSERT INTO artifacts (
                artifact_id, project_id, artifact_type, classification, sha256,
                is_original, cloud_policy, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                "project-evidence",
                "fixture",
                "INTERNAL",
                digest,
                1 if artifact_id == "input-artifact" else 0,
                "local_only",
                now,
            ),
        )

    service = ArtifactProvenanceService(repository)
    request = ArtifactProvenanceCreate(
        artifact_id="output-artifact",
        workflow_id=workflow.workflow_id,
        step_key="step",
        sha256="2" * 64,
        capability="local.text.analysis",
        model_id="fixture-model",
        parent_artifact_ids=["input-artifact"],
    )
    service.record(request)
    service.record(request)

    row = database.fetchone(
        "SELECT sha256, capability, model_id FROM artifact_provenance WHERE artifact_id = ?",
        ("output-artifact",),
    )
    assert row is not None
    assert row["sha256"] == "2" * 64
    assert row["capability"] == "local.text.analysis"
    assert row["model_id"] == "fixture-model"
    assert database.scalar("SELECT COUNT(*) FROM artifact_links") == 1

    with pytest.raises(ValueError, match="immutable"):
        service.record(request.model_copy(update={"sha256": "3" * 64}))
    database.close()


def test_handoff_return_continuation_is_bound_to_exact_checkpoint_digest(tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository = AutomationRepository(database)
    workflow = _workflow(WorkflowService(database), "continuation")
    digest = repository.latest_checkpoint_digest(workflow.workflow_id)
    now = datetime.now(UTC).isoformat()
    handoff_id = "handoff-continuation"
    database.execute(
        """
        INSERT INTO handoffs (
            handoff_id, template_id, title, objective_summary, status,
            request_digest, package_digest, manifest_json, preview_json,
            prepare_idempotency_key, created_at, updated_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', '{}', ?, ?, ?, ?)
        """,
        (
            handoff_id,
            "workflow-deep-ai-v1",
            "Workflow continuation",
            "fixture",
            "Prepared",
            "a" * 64,
            "b" * 64,
            "handoff-continuation-v1",
            now,
            now,
            now,
        ),
    )

    service = WorkflowContinuationService(repository)
    with pytest.raises(ValueError, match="digest mismatch"):
        service.prepare(
            WorkflowContinuationCreate(
                workflow_id=workflow.workflow_id,
                step_key="step",
                handoff_id=handoff_id,
                checkpoint_digest="0" * 64,
            )
        )

    continuation_id = service.prepare(
        WorkflowContinuationCreate(
            workflow_id=workflow.workflow_id,
            step_key="step",
            handoff_id=handoff_id,
            checkpoint_digest=digest,
        )
    )
    assert continuation_id

    return_id = "return-continuation"
    database.execute(
        """
        INSERT INTO returns (
            return_id, handoff_id, status, provider, request_digest, package_digest,
            manifest_digest, changed_file_count, event_count, validation_checks_json,
            preview_json, idempotency_key, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, '{}', '{}', ?, ?, ?)
        """,
        (
            return_id,
            handoff_id,
            "Validated",
            "fixture",
            "a" * 64,
            "b" * 64,
            "c" * 64,
            "return-continuation-v1",
            now,
            now,
        ),
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        service.bind_return(
            handoff_id=handoff_id,
            return_id=return_id,
            checkpoint_digest="f" * 64,
        )

    service.bind_return(
        handoff_id=handoff_id,
        return_id=return_id,
        checkpoint_digest=digest,
    )
    row = database.fetchone(
        "SELECT status, return_id FROM workflow_handoff_continuations WHERE continuation_id = ?",
        (continuation_id,),
    )
    assert row is not None
    assert row["status"] == "ReturnBound"
    assert row["return_id"] == return_id
    database.close()
