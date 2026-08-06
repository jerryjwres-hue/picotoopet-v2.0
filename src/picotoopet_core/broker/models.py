"""Phase 10B-B Broker Session 与严格 Mock Return 信封模型。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BrokerSessionStatus(StrEnum):
    """Windows Mock Dev Broker 的固定状态集合。"""

    RESERVED    = "reserved"
    RUNNING     = "running"
    RETURNING   = "returning"
    COMPLETED   = "completed"
    CANCELLED   = "cancelled"
    TIMED_OUT   = "timed_out"
    FAILED      = "failed"
    QUARANTINED = "quarantined"


class BrokerSessionRecord(BaseModel):
    """Control Center 可读取的 Broker Session 安全投影。"""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    handoff_id: str = Field(min_length=1, max_length=80)
    status: BrokerSessionStatus
    provider: Literal["local-mock-dev-broker"]
    timeout_seconds: Literal[30] = 30
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    return_id: str | None = Field(default=None, max_length=80)
    event_count: int = Field(default=0, ge=0, le=16)
    sandbox_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    failure_code: str | None = Field(
        default=None,
        pattern=r"^[A-Z0-9_]{1,80}$",
    )
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
    execution_notice: str = Field(min_length=1, max_length=280)


class BrokerSessionCreateResult(BaseModel):
    """仅创建响应携带 capability；列表和读取接口不包含该字段。"""

    model_config = ConfigDict(extra="forbid")

    record: BrokerSessionRecord
    capability: str = Field(pattern=r"^[0-9a-f]{64}$")


class BrokerReturnFileName(StrEnum):
    """Mock Return 允许的固定文件名；不存在自由路径字段。"""

    RETURN_MANIFEST = "return_manifest.json"
    SESSION_EVENTS  = "session_events.ndjson"
    SUMMARY         = "summary.md"
    CHANGED_FILES   = "changed_files.json"
    TEST_REPORT     = "test_report.json"
    BUILD_REPORT    = "build_report.json"
    SECURITY_REPORT = "security_report.json"
    QUESTIONS       = "questions.md"
    CHANGE_PROOF    = "changes/docs/mock-provider-proof.txt"
    SIGNATURE       = "signatures/manifest.sha256"


class BrokerReturnFile(BaseModel):
    """严格 UTF-8 文本条目；不接受 base64、二进制或任意路径。"""

    model_config = ConfigDict(extra="forbid")

    name: BrokerReturnFileName
    content: str = Field(max_length=32 * 1024)

    @field_validator("content")
    @classmethod
    def reject_nul(cls, value: str) -> str:
        """NUL 会破坏文本与路径边界，必须在模型层拒绝。"""

        if "\x00" in value:
            raise ValueError("Return 文本包含 NUL。")
        return value


class MockBrokerReturnEnvelope(BaseModel):
    """Windows Broker 可提交的唯一 Return 请求正文。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    session_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    handoff_id: str = Field(min_length=1, max_length=80)
    return_id: str = Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    provider: Literal["local-mock-dev-broker"]
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    sandbox_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    files: list[BrokerReturnFile] = Field(min_length=10, max_length=10)

    @model_validator(mode="after")
    def require_exact_file_set(self) -> "MockBrokerReturnEnvelope":
        """文件名必须完整、无重复，且与固定枚举完全一致。"""

        names = [item.name for item in self.files]
        if len(set(names)) != len(names) or set(names) != set(BrokerReturnFileName):
            raise ValueError("Mock Return 文件集合不符合固定合同。")
        total_bytes = sum(len(item.content.encode("utf-8")) for item in self.files)
        if total_bytes > 128 * 1024:
            raise ValueError("Mock Return 总大小超过 128 KiB。")
        return self
