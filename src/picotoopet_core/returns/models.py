"""Phase 10B/10D Return 包条目、状态和安全投影模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReturnEntryKind(StrEnum):
    """验证器可识别的包条目类型；当前合同只允许普通文件。"""

    FILE = "file"
    SYMLINK = "symlink"
    HARDLINK = "hardlink"
    DEVICE = "device"


@dataclass(frozen=True, slots=True)
class ReturnPackageEntry:
    """仅在 Mac Core 内存中存在的 Return 包条目。"""

    content: bytes
    kind: ReturnEntryKind = ReturnEntryKind.FILE


class ReturnStatus(StrEnum):
    """Return 允许的最小状态集合。"""

    RECEIVED = "received"
    VALIDATING = "validating"
    CONTRACT_VALIDATED = "contract_validated"
    QUARANTINED = "quarantined"


class ReturnValidationCheck(BaseModel):
    """Control Center 可展示的固定验证检查。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    passed: bool


class ReturnEventSummary(BaseModel):
    """脱敏、无原始 payload 的有界事件摘要。"""

    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1, le=100)
    event_type: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=160)


class ReturnRecord(BaseModel):
    """Windows 可读取的 Return 固定安全投影。"""

    model_config = ConfigDict(extra="forbid")

    return_id: str = Field(min_length=1, max_length=80)
    handoff_id: str = Field(min_length=1, max_length=80)
    status: ReturnStatus
    provider: Literal[
        "local-contract-self-test",
        "local-mock-dev-broker",
        "codex",
        "claude_code",
    ]
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    changed_file_count: int = Field(ge=0, le=5)
    event_count: int = Field(ge=0, le=100)
    validation_checks: list[ReturnValidationCheck] = Field(max_length=16)
    event_summaries: list[ReturnEventSummary] = Field(max_length=100)
    quarantine_code: str | None = Field(default=None, max_length=80)
    created_at: datetime
    updated_at: datetime
    execution_notice: str = Field(min_length=1, max_length=280)
