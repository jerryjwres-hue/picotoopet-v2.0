"""Strict durable contracts for Creative Intelligence."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreativeProfile(StrEnum):
    CONTENT_PLAN_V1 = "creative.content_plan.v1"


class CreativeJobStatus(StrEnum):
    READY = "Ready"
    IDEA_RANKING = "IdeaRanking"
    BRIEF_GENERATION = "BriefGeneration"
    SCRIPT_GENERATION = "ScriptGeneration"
    SHOT_PLANNING = "ShotPlanning"
    QUALITY_CHECK = "QualityCheck"
    CREATIVE_READY = "creative_ready"
    NEEDS_DEEP_AI = "NeedsDeepAI"
    NEEDS_HUMAN = "NeedsHuman"
    REJECTED = "Rejected"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


class CreativeStageKind(StrEnum):
    IDEA_RANKING = "idea_ranking.v1"
    CREATIVE_BRIEF = "creative_brief.v1"
    SCRIPT = "script.v1"
    SHOT_PLAN = "shot_plan.v1"


class CreativeQualityOutcome(StrEnum):
    PASS = "PASS"
    RETRY = "RETRY"
    NEEDS_DEEP_AI = "NEEDS_DEEP_AI"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    REJECT = "REJECT"


class CreativeRenderIntent(StrEnum):
    GENERATIVE_VIDEO = "GENERATIVE_VIDEO"
    GENERATIVE_IMAGE = "GENERATIVE_IMAGE"
    IMAGE_TO_VIDEO = "IMAGE_TO_VIDEO"
    PRODUCT_ASSET_COMPOSITE = "PRODUCT_ASSET_COMPOSITE"
    TEXT_CARD = "TEXT_CARD"
    EXISTING_ASSET = "EXISTING_ASSET"


class ClaimRisk(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CreativeJobCreateRequest(BaseModel):
    """Bounded user/business intent; never a model execution configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_result_package_ids: list[str] = Field(min_length=1, max_length=8)
    creative_profile: Literal["creative.content_plan.v1"] = "creative.content_plan.v1"
    creative_objective: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("source_result_package_ids")
    @classmethod
    def _source_ids_are_unique_uuids(cls, value: list[str]) -> list[str]:
        normalized = [str(UUID(item)) for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate source result package id")
        return normalized


class CreativeJobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creative_job_id: str
    project_key: str
    creative_profile: CreativeProfile
    creative_objective: str | None
    objective_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: CreativeJobStatus
    current_stage: CreativeStageKind | None = None
    creative_package_id: str | None = None
    deep_ai_handoff_id: str | None = None
    failure_code: str | None = None
    error_message: str | None = None
    idempotency_key: str
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None
