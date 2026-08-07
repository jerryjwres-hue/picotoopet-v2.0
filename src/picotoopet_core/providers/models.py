"""Phase 10D-A 受控 Codex Provider 的安全模型。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProviderUsageStatus(StrEnum):
    """用户从外部 Usage 页面人工确认的账户层状态。"""

    CONFIRMED_AVAILABLE = "confirmed_available"
    CONFIRMED_LOW = "confirmed_low"
    CONFIRMED_EXHAUSTED = "confirmed_exhausted"
    UNKNOWN = "unknown"


class ProviderReadinessStatus(StrEnum):
    """Mac 执行节点可公开的最小 Provider 就绪状态。"""

    READY = "ready"
    NOT_AUTHENTICATED = "not_authenticated"
    UNAVAILABLE = "unavailable"
    POLICY_BLOCKED = "policy_blocked"


class ProviderSessionStatus(StrEnum):
    """真实 Provider Session 的固定状态集合。"""

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
    """Mac Core 固定、客户端不可扩大的低预算。"""

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
    """不包含凭据或账户余额的 Provider 状态。"""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["codex"] = "codex"
    readiness: ProviderReadinessStatus
    real_execution_default: Literal[False] = False
    usage_machine_readable: Literal[False] = False
    execution_host: Literal["mac-worker"] = "mac-worker"
    message: str = Field(min_length=1, max_length=280)


class ProviderUsageConfirmationRequest(BaseModel):
    """Windows 唯一可提交的账户层人工确认。"""

    model_config = ConfigDict(extra="forbid")

    status: ProviderUsageStatus


class ProviderUsageConfirmationRecord(BaseModel):
    """绑定 Handoff digest、固定预算和短期过期时间的安全事实。"""

    model_config = ConfigDict(extra="forbid")

    confirmation_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    handoff_id: str = Field(min_length=1, max_length=80)
    provider: Literal["codex"] = "codex"
    status: ProviderUsageStatus
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    budget: ProviderBudget
    confirmed_at: datetime
    expires_at: datetime


class ProviderSessionRecord(BaseModel):
    """Windows 可读取的 Provider Session 安全投影。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    handoff_id: str = Field(min_length=1, max_length=80)
    provider: Literal["codex"] = "codex"
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
