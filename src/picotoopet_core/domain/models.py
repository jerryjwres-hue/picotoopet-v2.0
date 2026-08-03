"""API、队列和结果共享的 Pydantic 模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import Classification, CloudPolicy, TaskStatus


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    project_type: str = Field(min_length=1, max_length=100)
    source_app: str = Field(min_length=1, max_length=100)
    classification: Classification = Classification.INTERNAL
    workspace_root: str | None = None


class ProjectRecord(ProjectCreate):
    model_config = ConfigDict(from_attributes=True)

    project_id: str
    status: str
    created_at: datetime
    updated_at: datetime


class TaskCreate(BaseModel):
    project_id: str | None = None
    task_type: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=100, ge=0, le=1000)
    resource_tag: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=200)
    dedupe_key: str | None = Field(default=None, max_length=200)
    max_attempts: int = Field(default=3, ge=1, le=20)
    timeout_seconds: int = Field(default=3600, ge=1, le=86400)
    cloud_policy: CloudPolicy = CloudPolicy.LOCAL_ONLY


class TaskRecord(BaseModel):
    task_id: str
    parent_task_id: str | None = None
    project_id: str | None = None
    task_type: str
    status: TaskStatus
    priority: int
    resource_tag: str | None = None
    payload: dict[str, Any]
    result_id: str | None = None
    attempt_count: int
    max_attempts: int
    timeout_seconds: int
    created_at: datetime
    updated_at: datetime
    error_code: str | None = None
    error_message: str | None = None
