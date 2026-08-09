"""Phase 10E 受控远端发布与 Draft PR 的安全模型。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_COMMIT_PATTERN = r"^[0-9a-f]{40}$"
_UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_REPO_URL_PATTERN = r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
_REPO_SLUG_PATTERN = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
_BASE_REF_PATTERN = r"^(?!main$)(?!master$)[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$"
_REMOTE_REF_PATTERN = (
    r"^refs/heads/picotoopet/commit-candidates/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_REMOTE_BRANCH_PATTERN = (
    r"^picotoopet/commit-candidates/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_PR_URL_PATTERN = r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*$"


class ProviderPublicationStatus(StrEnum):
    """远端发布候选的封闭状态集合。"""

    WAITING_APPROVAL = "waiting_approval"
    QUEUED = "queued"
    PREFLIGHT = "preflight"
    PUSHING = "pushing"
    VERIFYING_REMOTE = "verifying_remote"
    REMOTE_READY = "remote_ready"
    CREATING_PR = "creating_pr"
    VERIFYING_PR = "verifying_pr"
    PR_READY = "pr_ready"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    BASE_MOVED = "base_moved"
    REMOTE_REF_CONFLICT = "remote_ref_conflict"
    AUTH_UNAVAILABLE = "auth_unavailable"
    POLICY_BLOCKED = "policy_blocked"
    PUSH_FAILED = "push_failed"
    PR_CONFLICT = "pr_conflict"
    PR_FAILED = "pr_failed"
    FAILED = "failed"


class ProviderPublicationCandidateRecord(BaseModel):
    """Windows 可读取的 Publication Candidate 安全事实。"""

    model_config = ConfigDict(extra="forbid")

    publication_candidate_id: str = Field(pattern=_UUID_PATTERN)
    commit_candidate_id: str = Field(pattern=_UUID_PATTERN)
    session_id: str = Field(pattern=_UUID_PATTERN)
    handoff_id: str = Field(pattern=_UUID_PATTERN)
    status: ProviderPublicationStatus
    repo_url: str = Field(pattern=_REPO_URL_PATTERN, max_length=240)
    repository_slug: str = Field(pattern=_REPO_SLUG_PATTERN, max_length=200)
    base_ref: str = Field(pattern=_BASE_REF_PATTERN, max_length=200)
    base_commit: str = Field(pattern=_COMMIT_PATTERN)
    commit_sha: str = Field(pattern=_COMMIT_PATTERN)
    change_set_digest: str = Field(pattern=_SHA256_PATTERN)
    remote_ref: str = Field(pattern=_REMOTE_REF_PATTERN, max_length=240)
    remote_branch: str = Field(pattern=_REMOTE_BRANCH_PATTERN, max_length=220)
    approval_id: str = Field(pattern=_UUID_PATTERN)
    pr_title_digest: str = Field(pattern=_SHA256_PATTERN)
    pr_body_digest: str = Field(pattern=_SHA256_PATTERN)
    pr_number: int | None = Field(default=None, ge=1)
    pr_url: str | None = Field(default=None, pattern=_PR_URL_PATTERN, max_length=320)
    pr_head_sha: str | None = Field(default=None, pattern=_COMMIT_PATTERN)
    validation_checks: list[str] = Field(default_factory=list, max_length=32)
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z0-9_]{1,80}$")
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None

    @model_validator(mode="after")
    def validate_pr_ready_identity(self) -> "ProviderPublicationCandidateRecord":
        """`pr_ready` 必须携带已经独立核验的 PR 身份。"""

        if self.status is ProviderPublicationStatus.PR_READY:
            if self.pr_number is None or self.pr_url is None or self.pr_head_sha is None:
                raise ValueError("pr_ready 缺少 PR 身份。")
            if self.pr_head_sha != self.commit_sha:
                raise ValueError("pr_ready 的 head SHA 必须等于批准的 commit SHA。")
        return self
