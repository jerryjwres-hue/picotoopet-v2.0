from __future__ import annotations

from picotoopet_core.creative.models import CreativeQualityOutcome, CreativeStageKind
from picotoopet_core.creative.profiles import creative_profile_definition
from picotoopet_core.creative.quality import CreativeQualityGate
from picotoopet_core.creative.source import CreativeSourceFinding, NormalizedCreativeSourceSet


def _source() -> NormalizedCreativeSourceSet:
    finding = CreativeSourceFinding(
        source_finding_ref="11111111-1111-4111-8111-111111111111:finding:1",
        result_package_id="11111111-1111-4111-8111-111111111111",
        result_digest="a" * 64,
        work_package_id="22222222-2222-4222-8222-222222222222",
        finding_rank=1,
        finding_digest="b" * 64,
        finding={
            "rank": 1,
            "title": "Drying time",
            "insight": "Customers mention drying time.",
            "confidence": 0.9,
            "evidence_ids": ["reviews:key:r1"],
        },
        evidence_ids=["reviews:key:r1"],
    )
    return NormalizedCreativeSourceSet(
        project_key="pet-dryer-us",
        result_package_ids=[finding.result_package_id],
        result_digests=[finding.result_digest],
        findings=[finding],
        evidence_ids=["reviews:key:r1"],
        source_set_digest="c" * 64,
    )


def _idea_result(source_ref: str) -> dict[str, object]:
    ideas = []
    for index in range(1, 4):
        ideas.append(
            {
                "idea_id": f"idea-{index:03d}",
                "rank": index,
                "title": f"Idea {index}",
                "audience_problem": "Drying a large dog takes too long.",
                "hook": "How long does drying take?",
                "angle": "time saved",
                "value_proposition": "faster drying",
                "format_hint": "short-form education",
                "confidence": 0.8,
                "source_finding_refs": [source_ref],
                "source_evidence_ids": ["reviews:key:r1"],
                "claim_risk": "LOW",
                "warnings": [],
            }
        )
    return {
        "schema_version": "1.0",
        "creative_profile": "creative.content_plan.v1",
        "ideas": ideas,
        "needs_deep_ai": False,
        "needs_human": False,
    }


def test_idea_quality_retries_unknown_source_finding_ref() -> None:
    source = _source()
    gate = CreativeQualityGate()
    decision, parsed = gate.evaluate(
        stage_kind=CreativeStageKind.IDEA_RANKING,
        profile=creative_profile_definition("creative.content_plan.v1"),
        source_set=source,
        previous_stages={},
        raw_result=_idea_result("missing:finding:1"),
    )
    assert decision.outcome is CreativeQualityOutcome.RETRY
    assert "UNKNOWN_SOURCE_FINDING_REF" in decision.reasons
    assert parsed is None


def test_idea_quality_passes_grounded_result() -> None:
    source = _source()
    raw = _idea_result(source.findings[0].source_finding_ref)
    decision, parsed = CreativeQualityGate().evaluate(
        stage_kind=CreativeStageKind.IDEA_RANKING,
        profile=creative_profile_definition("creative.content_plan.v1"),
        source_set=source,
        previous_stages={},
        raw_result=raw,
    )
    assert decision.outcome is CreativeQualityOutcome.PASS
    assert parsed is not None


def test_shot_plan_must_cover_every_script_beat() -> None:
    source = _source()
    previous = {
        "script.v1": {
            "schema_version": "1.0",
            "creative_profile": "creative.content_plan.v1",
            "script_id": "script-001",
            "title": "Fast dry",
            "target_duration_seconds": 10,
            "beats": [
                {
                    "beat_id": "beat-001",
                    "order": 1,
                    "duration_seconds": 5,
                    "voiceover": "Bath done.",
                    "on_screen_text": None,
                    "visual_intent": "wet dog",
                    "claim_source_evidence_ids": [],
                    "unsupported_claim": False,
                },
                {
                    "beat_id": "beat-002",
                    "order": 2,
                    "duration_seconds": 5,
                    "voiceover": "Dry faster.",
                    "on_screen_text": None,
                    "visual_intent": "dry dog",
                    "claim_source_evidence_ids": ["reviews:key:r1"],
                    "unsupported_claim": False,
                },
            ],
            "cta_beat_id": "beat-002",
            "warnings": [],
            "needs_deep_ai": False,
            "needs_human": False,
        }
    }
    raw = {
        "schema_version": "1.0",
        "creative_profile": "creative.content_plan.v1",
        "shots": [
            {
                "shot_id": "shot-001",
                "beat_id": "beat-001",
                "order": 1,
                "duration_seconds": 5,
                "subject": "wet dog",
                "environment": "grooming area",
                "action": "waits",
                "framing": "medium",
                "lighting_style": "soft",
                "continuity_keys": ["dog"],
                "required_facts": [],
                "source_evidence_ids": [],
                "text_reference": None,
                "production_notes": "renderer-neutral",
                "render_intent": "GENERATIVE_VIDEO",
            }
        ],
        "warnings": [],
        "needs_deep_ai": False,
        "needs_human": False,
    }
    decision, _ = CreativeQualityGate().evaluate(
        stage_kind=CreativeStageKind.SHOT_PLAN,
        profile=creative_profile_definition("creative.content_plan.v1"),
        source_set=source,
        previous_stages=previous,
        raw_result=raw,
    )
    assert decision.outcome is CreativeQualityOutcome.RETRY
    assert "SCRIPT_BEAT_NOT_COVERED" in decision.reasons
