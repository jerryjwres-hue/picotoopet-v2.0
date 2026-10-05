"""Phase 10A/10D Handoff preparation, preview and approval-bound models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

HandoffTemplateId = Literal[
    "picotoopet-repo-maintenance-v1",
    "picotoopet-repo-maintenance-codex-v1",
    "picotoopet-repo-maintenance-claude-code-v1",
]
HandoffProvider = Literal["manual", "codex", "claude_code"]


class HandoffStatus(StrEnum):
    """Handoff 允许的状态集合。"""

    PREPARED = "prepared"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class HandoffTemplate(BaseModel):
    """Mac Core 发布的固定安全模板；Windows 不复制模板事实。"""

    model_config = ConfigDict(extra="forbid")

    template_id: HandoffTemplateId
    display_name: str = Field(min_length=1, max_length=120)
    provider: HandoffProvider
    provider_configured: bool = False
    repo_url: str
    base_ref: str
    base_commit: str = Field(pattern=r"^[0-9a-f]{40}$")


class HandoffPrepareRequest(BaseModel):
    """用户可编辑的有界 Handoff 准备参数。"""

    model_config = ConfigDict(extra="forbid")

    template_id: HandoffTemplateId
    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=1000)
    expires_seconds: int = Field(default=1800, ge=300, le=3600)

    @field_validator("title", "objective")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        """统一换行和空白，并拒绝不可见控制字符。"""

        normalized = " ".join(value.replace("\r", "\n").split())
        if not normalized:
            raise ValueError("文本不能为空。")
        if any(ord(character) < 32 for character in normalized):
            raise ValueError("文本包含控制字符。")
        return normalized


class HandoffRecord(BaseModel):
    """Control Center 可读取的固定安全投影。"""

    model_config = ConfigDict(extra="forbid")

    handoff_id: str
    template_id: HandoffTemplateId
    template_name: str
    title: str
    objective_summary: str
    status: HandoffStatus
    provider: HandoffProvider
    provider_configured: bool = False
    repo_url: str
    base_ref: str
    base_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    sensitivity: Literal["internal"]
    planned_read_count: int = Field(ge=0, le=16)
    planned_write_count: int = Field(ge=0, le=16)
    required_tests: list[str] = Field(max_length=16)
    budget_summary: str
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_id: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    security_boundaries: list[str] = Field(max_length=16)
