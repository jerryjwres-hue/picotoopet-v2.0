"""Phase 10B-A Return 包条目、状态和安全投影模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ReturnEntryKind(StrEnum):
    """验证器可识别的包条目类型；本切片只允许普通文件。"""

    FILE     = "file"
    SYMLINK  = "symlink"
    HARDLINK = "hardlink"
    DEVICE   = "device"


@dataclass(frozen=True, slots=True)
class ReturnPackageEntry:
    """仅在 Mac Core 内存中存在的 Return 包条目。"""

    content: bytes
    kind: ReturnEntryKind = ReturnEntryKind.FILE


class ReturnStatus(StrEnum):
    """Phase 10B-A 允许的最小 Return 状态集合。"""

    RECEIVED           = "received"
    VALIDATING         = "validating"
    CONTRACT_VALIDATED = "contract_validated"
    QUARANTINED        = "quarantined"


class ReturnValidationCheck(BaseModel):
    """Control Center 可展示的固定验证检查。"""

    name: str = Field(min_length=1, max_length=64)
    passed: bool


class ReturnEventSummary(BaseModel):
    """脱敏、无原始 payload 的有界事件摘要。"""

    sequence: int = Field(ge=1, le=16)
    event_type: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=160)


class ReturnRecord(BaseModel):
    """Windows 可读取的 Return 固定安全投影。"""

    return_id: str = Field(min_length=1, max_length=80)
    handoff_id: str = Field(min_length=1, max_length=80)
    status: ReturnStatus
    provider: str = Field(pattern=r"^local-contract-self-test$")
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    changed_file_count: int = Field(ge=0, le=0)
    event_count: int = Field(ge=0, le=16)
    validation_checks: list[ReturnValidationCheck] = Field(max_length=16)
    event_summaries: list[ReturnEventSummary] = Field(max_length=16)
    quarantine_code: str | None = Field(default=None, max_length=80)
    created_at: datetime
    updated_at: datetime
    execution_notice: str = Field(min_length=1, max_length=240)
