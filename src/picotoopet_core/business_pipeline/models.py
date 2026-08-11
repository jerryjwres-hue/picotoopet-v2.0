"""Strict contracts for the 2.3.21.1 end-to-end business pipeline."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BusinessAdapterProfile(StrEnum):
    AMAZON_REVIEWS_EXPORT_V1 = "amazon.reviews_export.v1"
    INSPIRATION_IDEAS_EXPORT_V1 = "inspiration.ideas_export.v1"


class BusinessPipelineStatus(StrEnum):
    READY = "Ready"
    BUSINESS_ANALYSIS = "BusinessAnalysis"
    CREATIVE_INTELLIGENCE = "CreativeIntelligence"
    AWAITING_GPU = "AwaitingGpu"
    RENDERING = "Rendering"
    QUALITY_CHECK = "QualityCheck"
    COMPLETED = "Completed"
    NEEDS_DEEP_AI = "NeedsDeepAI"
    NEEDS_HUMAN = "NeedsHuman"
    REJECTED = "Rejected"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


class BusinessPipelineQualityOutcome(StrEnum):
    PASS = "PASS"
    NEEDS_DEEP_AI = "NEEDS_DEEP_AI"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    REJECT = "REJECT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BusinessPipelineRunCreateRequest(BaseModel):
    """Producer-visible fields; renderer/model/provider authority is intentionally absent."""

    model_config = ConfigDict(extra="forbid")

    work_package_id: str = Field(min_length=1, max_length=128)
    adapter_profile: BusinessAdapterProfile
    idempotency_key: str = Field(min_length=1, max_length=256)


class BusinessPipelineRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pipeline_run_id: str
    work_package_id: str
    result_package_id: str | None = None
    creative_job_id: str | None = None
    creative_package_id: str | None = None
    production_job_id: str | None = None
    production_package_id: str | None = None
    return_package_id: str | None = None
    project_key: str
    producer_id: str
    producer_version: str
    adapter_profile: BusinessAdapterProfile
    status: BusinessPipelineStatus
    quality_outcome: BusinessPipelineQualityOutcome | None = None
    failure_code: str | None = None
    error_message: str | None = None
    idempotency_key: str
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class BusinessReturnPackageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_package_id: str
    pipeline_run_id: str
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_relpath: str
    manifest: dict[str, Any]
    quality_outcome: str
    created_at: datetime
