"""Shared safety models for bounded Codex and Claude Code provider sessions."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type ProviderName = Literal["codex", "claude_code"]


class ProviderUsageStatus(StrEnum):
    """Account-layer availability fact; it never contains credentials or balances."""

    CONFIRMED_AVAILABLE = "confirmed_available"
    CONFIRMED_LOW = "confirmed_low"
    CONFIRMED_EXHAUSTED = "confirmed_exhausted"
    UNKNOWN = "unknown"


class ProviderReadinessStatus(StrEnum):
    """Minimal non-secret provider readiness visible to Mac Core/Windows."""

    READY = "ready"
    NOT_AUTHENTICATED = "not_authenticated"
    UNAVAILABLE = "unavailable"
    POLICY_BLOCKED = "policy_blocked"


class ProviderSessionStatus(StrEnum):
    """Fixed lifecycle states for a real bounded provider session."""

    REQUESTED = "requested"
    WAITING_USAGE_CONFIRMATION = "waiting_usage_confirmation"
    WAITING_PROVIDER_READY = "waiting_provider_ready"
    STAGING = "staging"
    RUNNING = "running"
    RETURNING = "returning"
    VALIDATING = "validating"
    READY_FOR_REVIEW = "ready_for_review"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    STOPPED_BY_BUDGET = "stopped_by_budget"
    STOPPED_BY_POLICY = "stopped_by_policy"
    PROVIDER_FAILED = "provider_failed"
    RETURN_QUARANTINED = "return_quarantined"
    VALIDATION_FAILED = "validation_failed"
    FAILED = "failed"


class ProviderBudget(BaseModel):
    """Mac Core fixed low budget that no client can enlarge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_turns: Literal[8] = 8
    timeout_seconds: Literal[900] = 900
    max_changed_files: Literal[5] = 5
    max_file_bytes: Literal[65536] = 65536
    max_return_bytes: Literal[262144] = 262144
    automatic_retries: Literal[0] = 0
    concurrency: Literal[1] = 1
    network_tools_allowed: Literal[False] = False


class ProviderStatusRecord(BaseModel):
    """Non-secret readiness projection for one fixed coding provider."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderName = "codex"
    readiness: ProviderReadinessStatus
    real_execution_default: Literal[False] = False
    usage_machine_readable: Literal[False] = False
    execution_host: Literal["mac-worker"] = "mac-worker"
    message: str = Field(min_length=1, max_length=280)


class ProviderUsageConfirmationRequest(BaseModel):
    """Legacy account-layer availability confirmation; it cannot set execution policy."""

    model_config = ConfigDict(extra="forbid")

    status: ProviderUsageStatus


class ProviderUsageConfirmationRecord(BaseModel):
    """Availability fact bound to exact handoff digests and the fixed shared budget."""

    model_config = ConfigDict(extra="forbid")

    confirmation_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    handoff_id: str = Field(min_length=1, max_length=80)
    provider: ProviderName = "codex"
    status: ProviderUsageStatus
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget: ProviderBudget
    confirmed_at: datetime
    expires_at: datetime


class ProviderSessionRecord(BaseModel):
    """Windows-safe projection of one Codex or Claude Code session."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    handoff_id: str = Field(min_length=1, max_length=80)
    provider: ProviderName = "codex"
    status: ProviderSessionStatus
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget: ProviderBudget
    turns_used: int = Field(default=0, ge=0, le=8)
    elapsed_seconds: int = Field(default=0, ge=0, le=900)
    changed_file_count: int = Field(default=0, ge=0, le=5)
    return_id: str | None = Field(default=None, max_length=80)
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z0-9_]{1,80}$")
    provider_usage_unknown: bool = True
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    execution_notice: str = Field(min_length=1, max_length=360)
