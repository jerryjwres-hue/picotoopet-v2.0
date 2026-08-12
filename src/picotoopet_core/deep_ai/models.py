"""Strict durable models for paid-AI escalation and quality learning."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DeepAiEscalationStatus(StrEnum):
    PREPARED = "Prepared"
    WAITING_APPROVAL = "WaitingApproval"
    APPROVED = "Approved"
    PROVIDER_READY = "ProviderReady"
    CLAIMED = "Claimed"
    EXECUTING = "Executing"
    VALIDATING = "Validating"
    COMPLETED = "Completed"
    NEEDS_HUMAN = "NeedsHuman"
    REJECTED = "Rejected"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


class DeepAiAttemptStatus(StrEnum):
    RESERVED = "Reserved"
    SUBMITTED = "Submitted"
    COMPLETED = "Completed"
    AMBIGUOUS = "Ambiguous"
    FAILED = "Failed"


class DeepAiValidationOutcome(StrEnum):
    PASS = "PASS"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    REJECT = "REJECT"


class DeepAiHumanAction(StrEnum):
    ACCEPTED = "Accepted"
    REJECTED = "Rejected"
    MODIFIED = "Modified"
    NO_DECISION = "NoDecision"


class DeepAiEscalationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    escalation_job_id: str
    source_kind: str
    source_id: str
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: str
    sanitized_package_relpath: str
    sanitized_package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    sanitizer_version: str
    provider_profile_id: str
    provider_profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_id: str
    max_input_tokens: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0)
    max_calls: int = Field(ge=1, le=2)
    max_cost_usd: Decimal = Field(ge=Decimal("0"))
    status: DeepAiEscalationStatus
    approval_id: str | None = None
    approval_digest: str | None = None
    approval_expires_at: datetime | None = None
    validation_outcome: DeepAiValidationOutcome | None = None
    accepted_result_digest: str | None = None
    accepted_result_relpath: str | None = None
    failure_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class DeepAiAttemptRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    escalation_job_id: str
    attempt_number: int = Field(ge=1, le=2)
    status: DeepAiAttemptStatus
    estimated_cost_usd: Decimal = Field(ge=Decimal("0"))
    provider_request_id: str | None = None
    response_digest: str | None = None
    response_relpath: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    actual_cost_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    cost_source: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class DeepAiLearningEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    idempotency_key: str
    project_key: str
    source_kind: str
    source_id: str
    local_quality_outcome: str
    escalation_job_id: str | None = None
    human_action: DeepAiHumanAction
    reason_tags: list[str]
    final_content_digest: str | None = None
    created_at: datetime
