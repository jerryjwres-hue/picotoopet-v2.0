from __future__ import annotations

import pytest
from pydantic import ValidationError

from picotoopet_core.creative.models import (
    CreativeRenderIntent,
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
