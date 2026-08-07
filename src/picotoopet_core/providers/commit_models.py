"""Phase 10D-C 本地 Git Commit Candidate 的安全模型。"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_COMMIT_PATTERN = r"^[0-9a-f]{40,64}$"
_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_LOCAL_REF_PATTERN = r"^refs/picotoopet/commit-candidates/[0-9a-f-]{36}$"


class ProviderCommitStatus(StrEnum):
    """Commit Candidate 的固定状态集合。"""

    WAITING_APPROVAL = "waiting_approval"
    QUEUED = "queued"
    STAGING = "staging"
    REPLAYING = "replaying"
    VALIDATING = "validating"
    COMMITTING = "committing"
    COMMIT_READY = "commit_ready"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ARTIFACT_INVALID = "artifact_invalid"
    BASE_MISMATCH = "base_mismatch"
    POLICY_BLOCKED = "policy_blocked"
    VALIDATION_FAILED = "validation_failed"
    COMMIT_FAILED = "commit_failed"
    REF_CONFLICT = "ref_conflict"
    FAILED = "failed"


class ProviderCommitCandidateRecord(BaseModel):
    """Windows 可读取的本地提交候选安全事实。"""

    model_config = ConfigDict(extra="forbid")

    commit_candidate_id: str = Field(pattern=_UUID_PATTERN)
    adoption_candidate_id: str = Field(pattern=_UUID_PATTERN)
    session_id: str = Field(pattern=_UUID_PATTERN)
    return_id: str = Field(min_length=1, max_length=80)
    status: ProviderCommitStatus
    base_commit: str = Field(pattern=_COMMIT_PATTERN)
    change_set_digest: str = Field(pattern=_SHA256_PATTERN)
    approval_id: str = Field(pattern=_UUID_PATTERN)
    message_preview: str = Field(min_length=1, max_length=240)
    message_digest: str = Field(pattern=_SHA256_PATTERN)
    tree_sha: str | None = Field(default=None, pattern=_COMMIT_PATTERN)
    commit_sha: str | None = Field(default=None, pattern=_COMMIT_PATTERN)
    local_ref: str = Field(pattern=_LOCAL_REF_PATTERN)
    validation_checks: list[str] = Field(default_factory=list, max_length=24)
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z0-9_]{1,80}$")
    author_time_utc: datetime | None = None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
