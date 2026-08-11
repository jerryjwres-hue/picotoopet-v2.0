"""Durable workflow foundation retained through the current production schema."""

from __future__ import annotations

from pathlib import Path

import pytest

from picotoopet_core.automation.dag import topological_order
from picotoopet_core.automation.models import (
    CapabilityRegistration,
    QualityDecision,
    QualityOutcome,
    WorkflowCreate,
    WorkflowStepCreate,
)
from picotoopet_core.automation.service import WorkflowService
from picotoopet_core.db.database import Database


def _open_database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "picotoopet.sqlite3")
    database.open()
    database.apply_migrations()
    return database


def test_workflow_replay_survives_restart_after_current_schema(tmp_path: Path) -> None:
    database = _open_database(tmp_path)
    service = WorkflowService(database)
    request = WorkflowCreate(
        project_id=None,
        name="foundation-smoke",
        priority=50,
        max_concurrency=2,
        idempotency_key="foundation-smoke-v1",
        steps=[
            WorkflowStepCreate(step_key="collect", task_type="system.diagnostic_snapshot"),
            WorkflowStepCreate(
                step_key="review",
                task_type="system.diagnostic_snapshot",
                depends_on=["collect"],
            ),
        ],
    )

    created = service.create_workflow(request)
    assert created.status.value == "Ready"
    assert [step.step_key for step in created.steps] == ["collect", "review"]
    assert database.scalar("SELECT MAX(version) FROM schema_migrations") == 14
    workflow_id = created.workflow_id
    database.close()

    reopened = _open_database(tmp_path)
    reloaded = WorkflowService(reopened).get_workflow(workflow_id)
    assert reloaded.workflow_id == workflow_id
    assert reloaded.idempotency_key == "foundation-smoke-v1"
    assert [step.step_key for step in reloaded.steps] == ["collect", "review"]
    reopened.close()


def test_dag_rejects_cycles_and_is_deterministic() -> None:
    assert topological_order({"a": (), "b": ("a",), "c": ("a", "b")}) == ["a", "b", "c"]
    with pytest.raises(ValueError, match="cycle"):
        topological_order({"a": ("b",), "b": ("a",)})
    with pytest.raises(ValueError, match="missing"):
        topological_order({"a": ("ghost",)})


def test_capability_and_quality_contracts_are_typed() -> None:
    registration = CapabilityRegistration(
        worker_id="mac-worker",
        capability="local.text.analysis",
        task_types=["system.diagnostic_snapshot"],
        healthy=True,
    )
    assert registration.capability == "local.text.analysis"

    decision = QualityDecision(
        workflow_id="wf-1",
        step_key="review",
        outcome=QualityOutcome.NEEDS_DEEP_AI,
        rule_id="confidence-threshold",
        evidence={"score": 0.41},
    )
    assert decision.outcome is QualityOutcome.NEEDS_DEEP_AI
