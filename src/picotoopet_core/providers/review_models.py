"""Phase 10D-B Return 审阅与落地候选的安全模型。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_COMMIT_PATTERN = r"^[0-9a-f]{40,64}$"
_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


class ProviderReviewDecision(StrEnum):
    """人工审阅只允许不可反转的接受或拒绝。"""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ProviderAdoptionStatus(StrEnum):
    """落地候选的固定状态集合。"""

    QUEUED = "queued"
    STAGING = "staging"
    APPLYING = "applying"
    VALIDATING = "validating"
    ADOPTION_READY = "adoption_ready"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ARTIFACT_INVALID = "artifact_invalid"
    BASE_MISMATCH = "base_mismatch"
    POLICY_BLOCKED = "policy_blocked"
    VALIDATION_FAILED = "validation_failed"
    FAILED = "failed"


class ProviderReturnArtifactRecord(BaseModel):
    """可公开的 artifact 元数据，不包含文件或 diff 正文。"""

    model_config = ConfigDict(extra="forbid")

    return_id: str = Field(min_length=1, max_length=80)
    session_id: str = Field(pattern=_UUID_PATTERN)
    handoff_id: str = Field(min_length=1, max_length=80)
    base_commit: str = Field(pattern=_COMMIT_PATTERN)
    change_set_digest: str = Field(pattern=_SHA256_PATTERN)
    review_diff_digest: str = Field(pattern=_SHA256_PATTERN)
    changed_file_count: int = Field(ge=0, le=5)
    payload_bytes: int = Field(ge=0, le=262144)
    artifact_status: Literal["reviewable", "legacy_no_artifact", "invalid"]
    created_at: datetime


class ProviderReviewDecisionRecord(BaseModel):
    """绑定精确 change-set digest 的人工审阅事实。"""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(pattern=_UUID_PATTERN)
    session_id: str = Field(pattern=_UUID_PATTERN)
    return_id: str = Field(min_length=1, max_length=80)
    decision: ProviderReviewDecision
    change_set_digest: str = Field(pattern=_SHA256_PATTERN)
    created_at: datetime


class ProviderAdoptionCandidateRecord(BaseModel):
    """Windows 可读取的落地候选安全投影。"""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(pattern=_UUID_PATTERN)
    session_id: str = Field(pattern=_UUID_PATTERN)
    return_id: str = Field(min_length=1, max_length=80)
    status: ProviderAdoptionStatus
    base_commit: str = Field(pattern=_COMMIT_PATTERN)
    change_set_digest: str = Field(pattern=_SHA256_PATTERN)
    changed_file_count: int = Field(ge=0, le=5)
    validation_checks: list[str] = Field(default_factory=list, max_length=20)
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z0-9_]{1,80}$")
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
