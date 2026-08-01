"""跨 REST、MCP 和 Connector 的冻结数据契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import ApprovalStatus, Classification, CloudPolicy, TaskStatus


class ContractModel(BaseModel):
    """所有外部契约统一拒绝未知字段。"""

    model_config = ConfigDict(extra="forbid")


class ProjectContract(ContractModel):
    """项目元数据契约。"""

    project_id: str
    title: str
    project_type: str
    source_app: str
    classification: Classification
    workspace_root: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class ArtifactContract(ContractModel):
    """资产登记契约；原始资产只登记，不承诺可修改。"""

    artifact_id: str
    project_id: str
    artifact_type: str
    classification: Classification
    source_path: str | None = None
    stored_object_hash: str | None = None
    media_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    is_original: bool = False
    cloud_policy: CloudPolicy = CloudPolicy.LOCAL_ONLY
    created_at: datetime


class TaskContract(ContractModel):
    """耐久任务契约。"""

    task_id: str
    parent_task_id: str | None = None
    project_id: str | None = None
    task_type: str
    status: TaskStatus
    priority: int = Field(ge=0, le=1000)
    resource_tag: str | None = None
    idempotency_key: str | None = None
    dedupe_key: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    result_id: str | None = None
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    timeout_seconds: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    error_code: str | None = None
    error_message: str | None = None


class ResultContract(ContractModel):
    """内容寻址结果契约。"""

    result_id: str
    project_id: str | None = None
    task_id: str | None = None
    result_type: str
    object_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest: dict[str, Any]
    schema_version: str
    created_at: datetime


class ApprovalContract(ContractModel):
    """不含明文令牌的审批持久化契约。"""

    approval_id: str
    task_id: str | None = None
    approval_type: str
    scope: dict[str, Any]
    status: ApprovalStatus
    requested_by: str
    resolved_by: str | None = None
    expires_at: datetime
    requested_at: datetime
    resolved_at: datetime | None = None
    decision_reason: str | None = None


class ConnectorEventContract(ContractModel):
    """Maotai、创作助手和 Windows Worker 的统一事件契约。"""

    event_id: str
    connector_id: str
    event_type: str
    project_id: str | None = None
    classification: Classification
    payload: dict[str, Any]
    idempotency_key: str
    trace_id: str
    occurred_at: datetime
    schema_version: str = "2.2.0"
