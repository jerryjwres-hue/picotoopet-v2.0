"""Authenticated durable automation platform routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, status

from picotoopet_core.automation.models import (
    AutomationDiagnosticsSnapshot,
    AutomationHealthSnapshot,
    CapabilityRecord,
    CapabilityRegistration,
    DiagnosticFact,
    QualityDecision,
    QualityDecisionRecord,
    WorkflowCreate,
    WorkflowRecord,
)
from picotoopet_core.security.auth import require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/workflows", response_model=WorkflowRecord, status_code=status.HTTP_201_CREATED)
def create_workflow(payload: WorkflowCreate, request: Request) -> WorkflowRecord:
    """Persist a replay-safe workflow definition without executing it inline."""

    return request.app.state.services.workflows.create_workflow(payload)


@router.get("/workflows", response_model=list[WorkflowRecord])
def list_workflows(request: Request, limit: int = 200) -> list[WorkflowRecord]:
    return request.app.state.services.workflows.list_workflows(limit=limit)


@router.get("/workflows/{workflow_id}", response_model=WorkflowRecord)
def get_workflow(workflow_id: str, request: Request) -> WorkflowRecord:
    return request.app.state.services.workflows.get_workflow(workflow_id)


@router.post("/workflows/{workflow_id}/reconcile", response_model=WorkflowRecord)
def reconcile_workflow(workflow_id: str, request: Request) -> WorkflowRecord:
    return request.app.state.services.workflows.reconcile(workflow_id)


@router.post("/workflows/{workflow_id}/pause", response_model=WorkflowRecord)
def pause_workflow(workflow_id: str, request: Request) -> WorkflowRecord:
    return request.app.state.services.workflows.pause(workflow_id)


@router.post("/workflows/{workflow_id}/resume", response_model=WorkflowRecord)
def resume_workflow(workflow_id: str, request: Request) -> WorkflowRecord:
    return request.app.state.services.workflows.resume(workflow_id)


@router.post("/workflows/{workflow_id}/cancel", response_model=WorkflowRecord)
def cancel_workflow(workflow_id: str, request: Request) -> WorkflowRecord:
    return request.app.state.services.workflows.cancel(workflow_id)


@router.post("/automation/capabilities", response_model=CapabilityRecord)
def register_capability(
    payload: CapabilityRegistration,
    request: Request,
) -> CapabilityRecord:
    """Register/heartbeat a typed capability; this endpoint cannot invoke providers."""

    return request.app.state.services.capability_router.register(payload)


@router.get("/automation/capabilities", response_model=list[CapabilityRecord])
def list_capabilities(request: Request) -> list[CapabilityRecord]:
    return request.app.state.services.capability_router.list()


@router.post("/automation/quality", response_model=QualityDecisionRecord)
def quality_decision(
    payload: QualityDecision,
    request: Request,
) -> QualityDecisionRecord:
    return request.app.state.services.quality_gate.decide(payload)


@router.get("/automation/health", response_model=AutomationHealthSnapshot)
def automation_health(request: Request) -> AutomationHealthSnapshot:
    database = request.app.state.services.database
    workflow_counts = {
        row["status"]: int(row["count"])
        for row in database.fetchall(
            "SELECT status, COUNT(*) AS count FROM workflow_runs GROUP BY status ORDER BY status"
        )
    }
    task_counts = {
        row["status"]: int(row["count"])
        for row in database.fetchall(
            "SELECT status, COUNT(*) AS count FROM tasks GROUP BY status ORDER BY status"
        )
    }
    return AutomationHealthSnapshot(
        workflow_counts=workflow_counts,
        task_counts=task_counts,
        capabilities=request.app.state.services.capability_router.list(),
        database_schema_version=int(
            database.scalar("SELECT COALESCE(MAX(version), 0) FROM schema_migrations") or 0
        ),
    )


@router.get("/automation/diagnostics", response_model=AutomationDiagnosticsSnapshot)
def automation_diagnostics(
    request: Request,
    limit: int = 100,
) -> AutomationDiagnosticsSnapshot:
    rows = request.app.state.services.automation_repository.recent_diagnostic_rows(limit=limit)
    return AutomationDiagnosticsSnapshot(
        facts=[
            DiagnosticFact(
                workflow_id=row["workflow_id"],
                step_key=row["step_key"],
                task_id=row["task_id"],
                status=row["status"],
                error_code=row["error_code"],
                error_message=row["error_message"],
                trace_id=row["trace_id"],
                updated_at=datetime.fromisoformat(row["updated_at"]).astimezone(UTC),
            )
            for row in rows
        ]
    )
