from __future__ import annotations

import pytest
from pydantic import ValidationError

from picotoopet_core.creative.models import (
    CreativeBriefResult,
    CreativeRenderIntent,
    CreativeStageKind,
    IdeaRankingResult,
    ShotPlanItem,
)
from picotoopet_core.creative.profiles import creative_profile_definition


def test_profile_registry_rejects_arbitrary_profile() -> None:
    with pytest.raises(ValueError):
        creative_profile_definition("creative.free_prompt.v1")


def test_idea_ranking_requires_three_to_ten_ranked_ideas() -> None:
    one = {
        "schema_version": "1.0",
        "creative_profile": "creative.content_plan.v1",
        "ideas": [
            {
                "idea_id": "idea-001",
                "rank": 1,
                "title": "Fast dry",
                "audience_problem": "Drying takes too long",
                "hook": "How long does a golden retriever take to dry?",
                "angle": "time saved",
                "value_proposition": "faster drying",
                "format_hint": "short-form product education",
                "confidence": 0.9,
                "source_finding_refs": ["result:finding:1"],
                "source_evidence_ids": ["reviews:key:r1"],
                "claim_risk": "LOW",
                "warnings": [],
            }
        ],
        "needs_deep_ai": False,
        "needs_human": False,
    }
    with pytest.raises(ValidationError):
        IdeaRankingResult.model_validate(one)


def test_shot_plan_rejects_non_renderer_neutral_intent() -> None:
    shot = {
        "shot_id": "shot-001",
        "beat_id": "beat-001",
        "order": 1,
        "duration_seconds": 3.0,
        "subject": "wet golden retriever",
        "environment": "home grooming area",
        "action": "dog waits after bath",
        "framing": "medium shot",
        "lighting_style": "natural soft light",
        "continuity_keys": ["golden-retriever"],
        "required_facts": [],
        "source_evidence_ids": [],
        "text_reference": None,
        "production_notes": "No executable renderer data.",
        "render_intent": "COMFY_WORKFLOW",
    }
    with pytest.raises(ValidationError):
        ShotPlanItem.model_validate(shot)
    assert CreativeRenderIntent.GENERATIVE_VIDEO.value == "GENERATIVE_VIDEO"


def test_profile_has_exact_four_stage_templates() -> None:
    profile = creative_profile_definition("creative.content_plan.v1")
    assert tuple(stage.stage_kind.value for stage in profile.stages) == (
        "idea_ranking.v1",
        "creative_brief.v1",
        "script.v1",
        "shot_plan.v1",
    )
    assert all(stage.max_model_attempts == 2 for stage in profile.stages)


def _brief(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1.0",
        "creative_profile": "creative.content_plan.v1",
        "selected_idea_id": "idea-001",
        "target_audience": "pet owners",
        "customer_problem": "slow drying",
        "value_proposition": "save time",
        "primary_hook": "Dry faster",
        "emotional_tone": "practical",
        "content_format": "short video",
        "duration_min_seconds": 10,
        "duration_max_seconds": 20,
        "message_hierarchy": ["problem", "solution"],
        "required_source_finding_refs": ["result:finding:1"],
        "required_source_evidence_ids": ["reviews:key:r1"],
        "prohibited_claims": [],
        "cta_intent": "learn more",
        "continuity_notes": [],
        "needs_deep_ai": False,
        "needs_human": False,
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize(
    "profile_id",
    ["video.landscape.v1", "video.vertical.v1", "video.square.v1"],
)
def test_creative_brief_accepts_only_closed_output_profile_ids(profile_id: str) -> None:
    parsed = CreativeBriefResult.model_validate(_brief(output_profile_id=profile_id))

    assert parsed.output_profile_id == profile_id


def test_creative_brief_defaults_legacy_payload_and_rejects_unknown_profile() -> None:
    parsed = CreativeBriefResult.model_validate(_brief())
    assert parsed.output_profile_id == "video.landscape.v1"

    with pytest.raises(ValidationError):
        CreativeBriefResult.model_validate(_brief(output_profile_id="video.custom.v1"))


def test_creative_brief_schema_exposes_closed_profile_without_renderer_dimensions() -> None:
    stage = creative_profile_definition("creative.content_plan.v1").stage(
        CreativeStageKind.CREATIVE_BRIEF
    )
    schema = stage.return_schema

    assert schema["properties"]["output_profile_id"]["default"] == "video.landscape.v1"
    assert "width" not in schema["properties"]
    assert "height" not in schema["properties"]
    assert "fps" not in schema["properties"]
