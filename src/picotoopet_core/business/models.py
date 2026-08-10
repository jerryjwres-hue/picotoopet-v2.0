"""Strict contracts for Work Package v1 and local business intelligence."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BusinessAnalysisProfile(StrEnum):
    """Closed business analysis profiles shipped by the product."""

    REVIEWS_VOICE_OF_CUSTOMER_V1 = "reviews.voice_of_customer.v1"
    IDEAS_PATTERN_ANALYSIS_V1 = "ideas.pattern_analysis.v1"


class BusinessWorkPackageStatus(StrEnum):
    RECEIVING = "Receiving"
    VALIDATING = "Validating"
    READY = "Ready"
    PREPROCESSING = "Preprocessing"
    LOCAL_INFERENCE = "LocalInference"
    QUALITY_CHECK = "QualityCheck"
    COMPLETED = "Completed"
    NEEDS_DEEP_AI = "NeedsDeepAI"
    NEEDS_HUMAN = "NeedsHuman"
    REJECTED = "Rejected"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


class BusinessRunStatus(StrEnum):
    READY = "Ready"
    PREPROCESSING = "Preprocessing"
    LOCAL_INFERENCE = "LocalInference"
    QUALITY_CHECK = "QualityCheck"
    COMPLETED = "Completed"
    NEEDS_DEEP_AI = "NeedsDeepAI"
    NEEDS_HUMAN = "NeedsHuman"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


class BusinessQualityOutcome(StrEnum):
    PASS = "PASS"
    RETRY = "RETRY"
    NEEDS_DEEP_AI = "NEEDS_DEEP_AI"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    REJECT = "REJECT"


_ALLOWED_MEDIA_TYPES = {
    "application/json",
    "application/jsonl",
    "application/x-ndjson",
    "text/csv",
    "text/plain",
}


class BusinessInputDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    path: str = Field(min_length=1, max_length=300)
    media_type: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0, le=256 * 1024 * 1024)
    record_key_field: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("path")
    @classmethod
    def _path_must_be_safe_input(cls, value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or not path.parts or path.parts[0] != "inputs":
            raise ValueError("input path must be relative under inputs/")
        if any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("unsafe input path")
        return path.as_posix()

    @field_validator("media_type")
    @classmethod
    def _media_type_is_closed(cls, value: str) -> str:
        if value not in _ALLOWED_MEDIA_TYPES:
            raise ValueError("unsupported business input media type")
        return value


class WorkPackageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(pattern=r"^1\.0$")
    package_id: str
    idempotency_key: str = Field(min_length=1, max_length=200)
    producer_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    producer_version: str = Field(min_length=1, max_length=80)
    created_at: datetime
    project_key: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.-]+$")
    analysis_profile: BusinessAnalysisProfile
    objective: str = Field(min_length=1, max_length=4000)
    inputs: list[BusinessInputDescriptor] = Field(min_length=1, max_length=64)

    @field_validator("package_id")
    @classmethod
    def _package_id_is_uuid(cls, value: str) -> str:
        return str(UUID(value))

    @model_validator(mode="after")
    def _unique_inputs(self) -> WorkPackageManifest:
        artifact_ids = [item.artifact_id for item in self.inputs]
        paths = [item.path for item in self.inputs]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("duplicate artifact_id")
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate input path")
        return self


class WorkPackageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_package_id: str
    idempotency_key: str
    producer_id: str
    producer_version: str
    project_key: str
    analysis_profile: BusinessAnalysisProfile
    objective: str
    status: BusinessWorkPackageStatus
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    compressed_size_bytes: int
    uncompressed_size_bytes: int | None = None
    package_object_relpath: str | None = None
    preprocess_digest: str | None = None
    result_package_id: str | None = None
    deep_ai_handoff_id: str | None = None
    failure_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class BusinessUploadSessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_session_id: str
    work_package_id: str
    source_digest: str
    total_size_bytes: int
    verified_size_bytes: int
    chunk_size_bytes: int
    status: str
    staging_relpath: str
    created_at: datetime
    updated_at: datetime
    finalized_at: datetime | None = None


class LocalIntelligenceRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    work_package_id: str
    status: BusinessRunStatus
    analysis_profile: BusinessAnalysisProfile
    source_digest: str
    preprocess_digest: str | None = None
    model_adapter_version: str
    configured_model_id: str
    template_version: str
    model_attempts: int
    quality_outcome: BusinessQualityOutcome | None = None
    failure_code: str | None = None
    error_message: str | None = None
    idempotency_key: str
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class BusinessResultPackageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_package_id: str
    work_package_id: str
    analysis_profile: BusinessAnalysisProfile
    source_digest: str
    preprocess_digest: str
    model_adapter_version: str
    configured_model_id: str
    template_version: str
    quality_outcome: BusinessQualityOutcome
    result_digest: str
    package_relpath: str
    result: dict[str, Any]
    warnings: list[str]
    created_at: datetime


class DeepAiHandoffRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handoff_id: str
    work_package_id: str
    source_digest: str
    preprocess_digest: str
    local_result_digest: str
    quality_reasons: list[str]
    return_schema: dict[str, Any]
    package_digest: str
    package_relpath: str
    status: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BusinessQualityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: BusinessQualityOutcome
    reasons: list[str] = Field(default_factory=list, max_length=20)
    correction_instruction: str | None = Field(default=None, max_length=2000)
