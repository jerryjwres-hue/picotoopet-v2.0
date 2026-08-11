"""Strict durable contracts for Creative Intelligence."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    """Bounded business intent; never a model execution configuration."""

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


class CreativeIdea(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idea_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    rank: int = Field(ge=1, le=10)
    title: str = Field(min_length=1, max_length=180)
    audience_problem: str = Field(min_length=1, max_length=1000)
    hook: str = Field(min_length=1, max_length=1000)
    angle: str = Field(min_length=1, max_length=800)
    value_proposition: str = Field(min_length=1, max_length=1000)
    format_hint: str = Field(min_length=1, max_length=300)
    confidence: float = Field(ge=0.0, le=1.0)
    source_finding_refs: list[str] = Field(min_length=1, max_length=20)
    source_evidence_ids: list[str] = Field(min_length=1, max_length=40)
    claim_risk: ClaimRisk
    warnings: list[str] = Field(default_factory=list, max_length=20)


class IdeaRankingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    creative_profile: Literal["creative.content_plan.v1"]
    ideas: list[CreativeIdea] = Field(min_length=3, max_length=10)
    needs_deep_ai: bool = False
    needs_human: bool = False

    @model_validator(mode="after")
    def _ranked_ideas_are_unique_and_consecutive(self) -> IdeaRankingResult:
        ranks = [item.rank for item in self.ideas]
        ids = [item.idea_id for item in self.ideas]
        if ranks != list(range(1, len(self.ideas) + 1)) or len(ids) != len(set(ids)):
            raise ValueError("idea ranks/ids must be unique and consecutive")
        return self


class CreativeBriefResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    creative_profile: Literal["creative.content_plan.v1"]
    selected_idea_id: str = Field(min_length=1, max_length=80)
    target_audience: str = Field(min_length=1, max_length=1000)
    customer_problem: str = Field(min_length=1, max_length=1000)
    value_proposition: str = Field(min_length=1, max_length=1000)
    primary_hook: str = Field(min_length=1, max_length=1000)
    emotional_tone: str = Field(min_length=1, max_length=300)
    content_format: str = Field(min_length=1, max_length=300)
    duration_min_seconds: int = Field(ge=3, le=600)
    duration_max_seconds: int = Field(ge=3, le=600)
    message_hierarchy: list[str] = Field(min_length=1, max_length=20)
    required_source_finding_refs: list[str] = Field(min_length=1, max_length=30)
    required_source_evidence_ids: list[str] = Field(min_length=1, max_length=50)
    prohibited_claims: list[str] = Field(default_factory=list, max_length=30)
    cta_intent: str = Field(min_length=1, max_length=500)
    continuity_notes: list[str] = Field(default_factory=list, max_length=30)
    needs_deep_ai: bool = False
    needs_human: bool = False

    @model_validator(mode="after")
    def _duration_order(self) -> CreativeBriefResult:
        if self.duration_min_seconds > self.duration_max_seconds:
            raise ValueError("duration range is inverted")
        return self


class ScriptBeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    order: int = Field(ge=1, le=100)
    duration_seconds: float = Field(gt=0.0, le=120.0)
    voiceover: str | None = Field(default=None, max_length=2000)
    on_screen_text: str | None = Field(default=None, max_length=800)
    visual_intent: str = Field(min_length=1, max_length=1200)
    claim_source_evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    unsupported_claim: bool = False


class CreativeScriptResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    creative_profile: Literal["creative.content_plan.v1"]
    script_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=180)
    target_duration_seconds: float = Field(gt=0.0, le=600.0)
    beats: list[ScriptBeat] = Field(min_length=1, max_length=60)
    cta_beat_id: str
    warnings: list[str] = Field(default_factory=list, max_length=30)
    needs_deep_ai: bool = False
    needs_human: bool = False

    @model_validator(mode="after")
    def _beats_are_consistent(self) -> CreativeScriptResult:
        ids = [item.beat_id for item in self.beats]
        orders = [item.order for item in self.beats]
        if len(ids) != len(set(ids)) or orders != list(range(1, len(self.beats) + 1)):
            raise ValueError("script beat ids/orders are invalid")
        if self.cta_beat_id not in set(ids):
            raise ValueError("cta beat must resolve")
        if abs(sum(item.duration_seconds for item in self.beats) - self.target_duration_seconds) > 5.0:
            raise ValueError("script beat duration does not match target")
        return self


class ShotPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    beat_id: str = Field(min_length=1, max_length=80)
    order: int = Field(ge=1, le=200)
    duration_seconds: float = Field(gt=0.0, le=120.0)
    subject: str = Field(min_length=1, max_length=1200)
    environment: str = Field(min_length=1, max_length=1200)
    action: str = Field(min_length=1, max_length=1200)
    framing: str = Field(min_length=1, max_length=500)
    lighting_style: str = Field(min_length=1, max_length=500)
    continuity_keys: list[str] = Field(default_factory=list, max_length=30)
    required_facts: list[str] = Field(default_factory=list, max_length=30)
    source_evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    text_reference: str | None = Field(default=None, max_length=800)
    production_notes: str = Field(default="renderer-neutral", max_length=1200)
    render_intent: CreativeRenderIntent


class ShotPlanResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    creative_profile: Literal["creative.content_plan.v1"]
    shots: list[ShotPlanItem] = Field(min_length=1, max_length=120)
    warnings: list[str] = Field(default_factory=list, max_length=30)
    needs_deep_ai: bool = False
    needs_human: bool = False

    @model_validator(mode="after")
    def _shots_are_ordered(self) -> ShotPlanResult:
        ids = [item.shot_id for item in self.shots]
        orders = [item.order for item in self.shots]
        if len(ids) != len(set(ids)) or orders != list(range(1, len(self.shots) + 1)):
            raise ValueError("shot ids/orders are invalid")
        return self


class CreativeQualityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: CreativeQualityOutcome
    reasons: list[str] = Field(default_factory=list, max_length=20)
    correction_instruction: str | None = Field(default=None, max_length=2000)


class CreativeStageRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_run_id: str
    creative_job_id: str
    stage_kind: CreativeStageKind
    status: str
    input_digest: str
    result_digest: str | None = None
    result: dict[str, Any] | None = None
    model_attempts: int
    quality_outcome: CreativeQualityOutcome | None = None
    failure_code: str | None = None
    error_message: str | None = None
    template_version: str
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class CreativePackageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creative_package_id: str
    creative_job_id: str
    source_set_digest: str
    package_digest: str
    package_relpath: str
    manifest: dict[str, Any]
    quality_outcome: CreativeQualityOutcome
    created_at: datetime


class CreativeDeepAiHandoffRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handoff_id: str
    creative_job_id: str
    stage_kind: CreativeStageKind
    source_set_digest: str
    failed_result_digest: str
    quality_reasons: list[str]
    return_schema: dict[str, Any]
    package_digest: str
    package_relpath: str
    status: str
    created_at: datetime


class CreativeEligibleSourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_package_id: str
    work_package_id: str
    project_key: str
    analysis_profile: str
    result_digest: str
    summary: str
    created_at: datetime
