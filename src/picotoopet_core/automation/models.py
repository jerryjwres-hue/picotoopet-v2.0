"""Durable automation-domain contracts for PicotooPet platform workflows."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SAFE_BUILTIN_WORKFLOW_TASK_TYPES = frozenset(
    {
        "system.noop",
        "system.diagnostic_snapshot",
    }
)


class WorkflowStatus(StrEnum):
    """Persisted workflow lifecycle."""

    DRAFT = "Draft"
    READY = "Ready"
    RUNNING = "Running"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    NEEDS_ATTENTION = "NeedsAttention"
    FAILED = "Failed"


class WorkflowStepStatus(StrEnum):
    """Persisted state for one workflow step."""

    PENDING = "Pending"
    BLOCKED = "Blocked"
    READY = "Ready"
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    RETRY_WAITING = "RetryWaiting"
    NEEDS_HUMAN = "NeedsHuman"
    NEEDS_DEEP_AI = "NeedsDeepAI"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"
    FAILED = "Failed"


class QualityOutcome(StrEnum):
    PASS = "PASS"
    RETRY = "RETRY"
    NEEDS_DEEP_AI = "NEEDS_DEEP_AI"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    REJECT = "REJECT"


class WorkflowStepCreate(BaseModel):
    """A closed queue-backed workflow step; task_type is data, never a shell command."""

    model_config = ConfigDict(extra="forbid")

    step_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    task_type: str = Field(min_length=1, max_length=100)
    depends_on: list[str] = Field(default_factory=list)
    required_capability: str | None = Field(default=None, min_length=1, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=20)
    timeout_seconds: int = Field(default=3600, ge=1, le=86400)

    @field_validator("depends_on")
    @classmethod
    def _unique_dependencies(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate workflow dependency")
        return value

    @model_validator(mode="after")
    def _require_capability_for_non_builtin_task_type(self) -> WorkflowStepCreate:
        if (
            self.task_type not in SAFE_BUILTIN_WORKFLOW_TASK_TYPES
            and self.required_capability is None
        ):
            raise ValueError(
                "required_capability is required for non-builtin workflow task_type"
            )
        return self


class WorkflowCreate(BaseModel):
    """Replay-safe workflow creation request."""

    model_config = ConfigDict(extra="forbid")

    project_id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    priority: int = Field(default=100, ge=0, le=1000)
    max_concurrency: int = Field(default=1, ge=1, le=32)
    idempotency_key: str = Field(min_length=1, max_length=200)
    steps: list[WorkflowStepCreate] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _unique_step_keys(self) -> WorkflowCreate:
        keys = [step.step_key for step in self.steps]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate workflow step_key")
        return self


class WorkflowStepRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    step_key: str
    ordinal: int
    task_type: str
    required_capability: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    status: WorkflowStepStatus
    task_id: str | None = None
    attempt_count: int
    max_attempts: int
    timeout_seconds: int
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    failure_code: str | None = None
    error_message: str | None = None


class WorkflowRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    project_id: str | None = None
    name: str
    status: WorkflowStatus
    priority: int
    max_concurrency: int
    idempotency_key: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_code: str | None = None
    steps: list[WorkflowStepRecord] = Field(default_factory=list)


class CapabilityRegistration(BaseModel):
    """Typed worker capability heartbeat. Registration never invokes a provider."""

    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=200)
    capability: str = Field(min_length=1, max_length=120)
    task_types: list[str] = Field(default_factory=list, max_length=100)
    healthy: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    heartbeat_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CapabilityRecord(CapabilityRegistration):
    registered_at: datetime


class QualityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    step_key: str
    outcome: QualityOutcome
    rule_id: str = Field(min_length=1, max_length=200)
    evidence: dict[str, Any] = Field(default_factory=dict)


class QualityDecisionRecord(QualityDecision):
    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ArtifactProvenanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    workflow_id: str
    step_key: str
    task_id: str | None = None
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    capability: str | None = None
    model_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    parent_artifact_ids: list[str] = Field(default_factory=list)


class WorkflowContinuationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    step_key: str
    handoff_id: str
    checkpoint_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class AutomationHealthSnapshot(BaseModel):
    workflow_counts: dict[str, int]
    task_counts: dict[str, int]
    capabilities: list[CapabilityRecord]
    database_schema_version: int
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DiagnosticFact(BaseModel):
    workflow_id: str | None = None
    step_key: str | None = None
    task_id: str | None = None
    status: str
    error_code: str | None = None
    error_message: str | None = None
    trace_id: str | None = None
    updated_at: datetime


class AutomationDiagnosticsSnapshot(BaseModel):
    facts: list[DiagnosticFact]
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
