"""Strict Goal video return contract and deterministic provenance validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
)

from picotoopet_core.creative.models import (
    CreativeBriefResult,
    CreativeScriptResult,
    IdeaRankingResult,
    ShotPlanResult,
)
from picotoopet_core.creative.quality import CreativeQualityGate
from picotoopet_core.creative.source import (
    CreativeSourceFinding,
    NormalizedCreativeSourceSet,
)

from .goal_handoff_access import GoalHandoffContext


class GoalVideoReturnError(ValueError):
    """A manual video return failed a fixed binding, provenance, or safety rule."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class GoalVideoReturnV1(BaseModel):
    """Bounded manual Web GPT return with no execution/configuration authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    goal_id: str = Field(min_length=1, max_length=128)
    handoff_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: str = Field(min_length=1, max_length=100)
    asset_allowlist_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    generated_at: datetime
    selected_direction: str = Field(min_length=1, max_length=500)
    reasoning_summary: str = Field(min_length=1, max_length=4000)
    verified_fact_ids: list[str] = Field(default_factory=list, max_length=128)
    inference_summary: str = Field(min_length=1, max_length=4000)
    creative_summary: str = Field(min_length=1, max_length=4000)
    image_prompt_summary: str = Field(min_length=1, max_length=4000)
    video_prompt_summary: str = Field(min_length=1, max_length=4000)
    continuity_constraints: list[str] = Field(default_factory=list, max_length=64)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=64)
    recommended_next_actions: list[str] = Field(default_factory=list, max_length=32)
    idea_ranking: IdeaRankingResult
    creative_brief: CreativeBriefResult
    script: CreativeScriptResult
    shot_plan: ShotPlanResult

    @model_serializer(mode="wrap")
    def _omit_legacy_null_asset_binding(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, object]:
        data = handler(self)
        if self.asset_allowlist_digest is None:
            data.pop("asset_allowlist_digest", None)
        return data

    @field_validator("verified_fact_ids")
    @classmethod
    def _unique_fact_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(not item or len(item) > 128 for item in value):
            raise ValueError("verified fact ids must be unique bounded strings")
        return value

    @field_validator(
        "continuity_constraints",
        "unresolved_questions",
        "recommended_next_actions",
    )
    @classmethod
    def _bounded_text_lists(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 1000 for item in value):
            raise ValueError("list values must be bounded non-empty strings")
        return value


@dataclass(frozen=True, slots=True)
class ValidatedGoalVideoReturn:
    return_digest: str
    source_set: NormalizedCreativeSourceSet
    stage_results: dict[str, dict[str, object]]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _source_set(
    context: GoalHandoffContext,
    *,
    return_digest: str,
) -> NormalizedCreativeSourceSet:
    source_package_id = next(iter(context.source_finding_refs.values())).split(":finding:")[0]
    work_package_id = str(
        uuid5(
            NAMESPACE_URL,
            f"picotoopet:goal-video-work:{context.goal_id}:{context.package_sha256}",
        )
    )
    findings = []
    for rank, evidence_id in enumerate(context.evidence_ids, start=1):
        finding = {
            "rank": rank,
            "evidence_ids": [evidence_id],
            "provenance": "autonomous.goal_handoff.v1",
        }
        findings.append(
            CreativeSourceFinding(
                source_finding_ref=context.source_finding_refs[evidence_id],
                result_package_id=source_package_id,
                result_digest=context.package_sha256,
                work_package_id=work_package_id,
                finding_rank=rank,
                finding_digest=_digest(finding),
                finding=finding,
                evidence_ids=[evidence_id],
            )
        )
    source_identity = {
        "goal_id": context.goal_id,
        "handoff_sha256": context.package_sha256,
        "prompt_version": context.prompt_version,
        "return_digest": return_digest,
        **(
            {
                "trusted_asset_ids": [item.asset_id for item in context.trusted_assets],
                "asset_allowlist_digest": context.asset_allowlist_digest,
            }
            if context.trusted_assets
            else {}
        ),
        "findings": [
            {
                "source_finding_ref": item.source_finding_ref,
                "finding_digest": item.finding_digest,
                "evidence_ids": item.evidence_ids,
            }
            for item in findings
        ],
    }
    return NormalizedCreativeSourceSet(
        project_key=f"autonomous-goal:{context.goal_id}",
        result_package_ids=[source_package_id],
        result_digests=[context.package_sha256],
        findings=findings,
        evidence_ids=list(context.evidence_ids),
        trusted_asset_ids=[item.asset_id for item in context.trusted_assets],
        source_set_digest=_digest(source_identity),
    )


def validate_goal_video_return(
    payload: GoalVideoReturnV1,
    context: GoalHandoffContext,
) -> ValidatedGoalVideoReturn:
    """Bind a strict return to one verified handoff and prepare Creative inputs."""

    if (
        payload.goal_id != context.goal_id
        or payload.handoff_sha256 != context.package_sha256
        or payload.prompt_version != context.prompt_version
    ):
        raise GoalVideoReturnError("HANDOFF_BINDING_MISMATCH")
    if not set(payload.verified_fact_ids).issubset(context.evidence_ids):
        raise GoalVideoReturnError("EVIDENCE_REFERENCE_INVALID")

    referenced_assets = {
        shot.existing_asset_ref
        for shot in payload.shot_plan.shots
        if shot.existing_asset_ref is not None
    }
    if payload.asset_allowlist_digest is not None and (
        payload.asset_allowlist_digest != context.asset_allowlist_digest
    ):
        raise GoalVideoReturnError("ASSET_ALLOWLIST_BINDING_MISMATCH")
    if referenced_assets:
        if payload.asset_allowlist_digest != context.asset_allowlist_digest:
            raise GoalVideoReturnError("ASSET_ALLOWLIST_BINDING_MISMATCH")
        allowed_assets = {item.asset_id for item in context.trusted_assets}
        if not referenced_assets <= allowed_assets:
            raise GoalVideoReturnError("UNKNOWN_EXISTING_ASSET_REF")

    canonical = payload.model_dump(mode="json")
    if CreativeQualityGate.contains_forbidden_output(canonical):
        raise GoalVideoReturnError("FORBIDDEN_AUTHORITY")
    return_digest = _digest(canonical)
    stage_results = {
        "idea_ranking.v1": payload.idea_ranking.model_dump(mode="json"),
        "creative_brief.v1": payload.creative_brief.model_dump(mode="json"),
        "script.v1": payload.script.model_dump(mode="json"),
        "shot_plan.v1": payload.shot_plan.model_dump(mode="json"),
    }
    return ValidatedGoalVideoReturn(
        return_digest=return_digest,
        source_set=_source_set(context, return_digest=return_digest),
        stage_results=stage_results,
    )
