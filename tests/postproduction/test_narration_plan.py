from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from picotoopet_core.postproduction.narration import (
    NarrationPlanError,
    NarrationPlanV1,
    NarrationSegmentPlan,
    compile_narration_plan,
    narration_plan_digest,
)
from picotoopet_core.production.compiler import compile_production_plan

PACKAGE_DIGEST = "b" * 64
PLAN_DIGEST = "d" * 64


def _manifest(
    beats: list[tuple[str, str | None]], shots: list[tuple[str, str, float]]
) -> dict[str, object]:
    total = sum(item[2] for item in shots)
    return {
        "schema_version": "1.0",
        "creative_package_id": str(uuid4()),
        "creative_job_id": str(uuid4()),
        "project_key": "pet-dryer-us",
        "creative_profile": "creative.content_plan.v1",
        "source_set_digest": "a" * 64,
        "quality_outcome": "PASS",
        "stage_results": {
            "creative_brief.v1": {
                "schema_version": "1.0",
                "creative_profile": "creative.content_plan.v1",
                "selected_idea_id": "idea-001",
                "target_audience": "pet owners",
                "customer_problem": "slow drying",
                "value_proposition": "save time",
                "primary_hook": "Dry faster",
                "emotional_tone": "practical",
                "content_format": "short video",
                "duration_min_seconds": 3,
                "duration_max_seconds": 30,
                "message_hierarchy": ["problem", "solution"],
                "required_source_finding_refs": ["result:finding:1"],
                "required_source_evidence_ids": ["reviews:key:r1"],
                "prohibited_claims": [],
                "cta_intent": "learn more",
                "continuity_notes": [],
                "output_profile_id": "video.landscape.v1",
                "needs_deep_ai": False,
                "needs_human": False,
            },
            "script.v1": {
                "schema_version": "1.0",
                "creative_profile": "creative.content_plan.v1",
                "script_id": "script-001",
                "title": "Dry faster",
                "target_duration_seconds": total,
                "beats": [
                    {
                        "beat_id": beat_id,
                        "order": index,
                        "duration_seconds": total / len(beats),
                        "voiceover": voiceover,
                        "on_screen_text": None,
                        "visual_intent": "A compact dryer in use",
                        "claim_source_evidence_ids": [],
                        "unsupported_claim": False,
                    }
                    for index, (beat_id, voiceover) in enumerate(beats, start=1)
                ],
                "cta_beat_id": beats[0][0],
                "warnings": [],
                "needs_deep_ai": False,
                "needs_human": False,
            },
            "shot_plan.v1": {
                "schema_version": "1.0",
                "creative_profile": "creative.content_plan.v1",
                "shots": [
                    {
                        "shot_id": shot_id,
                        "beat_id": beat_id,
                        "order": index,
                        "duration_seconds": duration,
                        "subject": "compact pet dryer",
                        "environment": "clean grooming area",
                        "action": "dryer turns",
                        "framing": "medium product shot",
                        "lighting_style": "soft daylight",
                        "continuity_keys": [],
                        "required_facts": [],
                        "source_evidence_ids": [],
                        "text_reference": None,
                        "production_notes": "renderer-neutral",
                        "render_intent": "GENERATIVE_VIDEO",
                    }
                    for index, (shot_id, beat_id, duration) in enumerate(shots, start=1)
                ],
                "warnings": [],
                "needs_deep_ai": False,
                "needs_human": False,
            },
        },
    }


def _compile(
    manifest: dict[str, object], *, plan_manifest: dict[str, object] | None = None, **kwargs
):  # type: ignore[no-untyped-def]
    # The Production plan is compiled from the authoritative manifest; narration may see a variant.
    source = plan_manifest or manifest
    plan = compile_production_plan(str(uuid4()), source, PACKAGE_DIGEST)
    manifest = {**manifest, "creative_package_id": plan.creative_package_id}
    return compile_narration_plan(
        production_plan=plan,
        production_plan_digest=kwargs.pop("production_plan_digest", PLAN_DIGEST),
        manifest=manifest,
        creative_package_digest=PACKAGE_DIGEST,
        **kwargs,
    )


def _plan_and_manifest(manifest: dict[str, object]):  # type: ignore[no-untyped-def]
    plan = compile_production_plan(str(uuid4()), manifest, PACKAGE_DIGEST)
    return plan, {**manifest, "creative_package_id": plan.creative_package_id}


def _two_beats() -> dict[str, object]:
    return _manifest(
        [("beat-1", "First line."), ("beat-2", "Second line.")],
        [("shot-1", "beat-1", 2.0), ("shot-2", "beat-1", 1.5), ("shot-3", "beat-2", 3.0)],
    )


def test_no_voiceover_is_valid_and_has_no_segments() -> None:
    manifest = _manifest(
        [("beat-1", None), ("beat-2", "   ")],
        [("shot-1", "beat-1", 2.0), ("shot-2", "beat-2", 2.0)],
    )
    plan = _compile(manifest)
    assert plan.narration_required is False
    assert plan.segments == []


def test_single_voiced_beat_gets_exact_window() -> None:
    plan = _compile(_manifest([("beat-1", "Drying time matters.")], [("shot-1", "beat-1", 3.0)]))
    assert plan.narration_required is True
    assert len(plan.segments) == 1
    segment = plan.segments[0]
    assert (segment.beat_id, segment.start_ms, segment.end_ms) == ("beat-1", 0, 3000)
    assert segment.text == "Drying time matters."
    assert plan.tts_profile_id == "narration.local.windows.v1"
    assert plan.voice_profile_id == "voice.windows.default.v1"


def test_same_beat_shots_form_one_spanning_window_and_beats_accumulate() -> None:
    plan = _compile(_two_beats())
    assert [(s.beat_id, s.start_ms, s.end_ms) for s in plan.segments] == [
        ("beat-1", 0, 3500),
        ("beat-2", 3500, 6500),
    ]
    assert [s.order for s in plan.segments] == [1, 2]
    assert plan.target_runtime_ms == 6500


def test_unvoiced_beat_still_advances_timeline() -> None:
    manifest = _manifest(
        [("beat-1", None), ("beat-2", "Only second.")],
        [("shot-1", "beat-1", 2.0), ("shot-2", "beat-2", 3.0)],
    )
    plan = _compile(manifest)
    assert [(s.beat_id, s.start_ms, s.end_ms) for s in plan.segments] == [("beat-2", 2000, 5000)]


def test_voiced_beat_without_shots_is_rejected() -> None:
    manifest = _two_beats()
    broken = deepcopy(manifest)
    for shot in broken["stage_results"]["shot_plan.v1"]["shots"]:  # type: ignore[index]
        shot["beat_id"] = "beat-1"
    with pytest.raises(NarrationPlanError) as caught:
        _compile(broken, plan_manifest=manifest)
    assert caught.value.code == "NARRATION_TIMELINE_AMBIGUOUS"


def test_shot_pointing_at_unknown_beat_is_rejected() -> None:
    manifest = _two_beats()
    broken = deepcopy(manifest)
    broken["stage_results"]["shot_plan.v1"]["shots"][2]["beat_id"] = "beat-x"  # type: ignore[index]
    with pytest.raises(NarrationPlanError) as caught:
        _compile(broken, plan_manifest=manifest)
    assert caught.value.code == "NARRATION_TIMELINE_AMBIGUOUS"


def test_non_contiguous_same_beat_shots_are_rejected() -> None:
    manifest = _manifest(
        [("beat-1", "One."), ("beat-2", "Two.")],
        [("shot-1", "beat-1", 1.0), ("shot-2", "beat-2", 1.0), ("shot-3", "beat-1", 1.0)],
    )
    with pytest.raises(NarrationPlanError) as caught:
        _compile(manifest)
    assert caught.value.code == "NARRATION_TIMELINE_AMBIGUOUS"


def test_beat_order_inversion_is_rejected() -> None:
    manifest = _manifest(
        [("beat-1", "One."), ("beat-2", "Two.")],
        [("shot-1", "beat-2", 1.0), ("shot-2", "beat-1", 1.0)],
    )
    with pytest.raises(NarrationPlanError) as caught:
        _compile(manifest)
    assert caught.value.code == "NARRATION_TIMELINE_AMBIGUOUS"


def test_final_segment_cannot_exceed_target_runtime() -> None:
    manifest = _two_beats()
    plan, source = _plan_and_manifest(manifest)
    shrunk = plan.model_copy(update={"target_runtime_ms": 6000})
    with pytest.raises(NarrationPlanError) as caught:
        compile_narration_plan(
            production_plan=shrunk,
            production_plan_digest=PLAN_DIGEST,
            manifest=source,
            creative_package_digest=PACKAGE_DIGEST,
        )
    assert caught.value.code == "NARRATION_TIMELINE_AMBIGUOUS"


def test_identity_mismatch_is_rejected() -> None:
    plan, source = _plan_and_manifest(_two_beats())
    for kwargs in (
        {
            "manifest": {**source, "creative_package_id": str(uuid4())},
            "creative_package_digest": PACKAGE_DIGEST,
        },
        {"manifest": source, "creative_package_digest": "e" * 64},
    ):
        with pytest.raises(NarrationPlanError) as caught:
            compile_narration_plan(
                production_plan=plan, production_plan_digest=PLAN_DIGEST, **kwargs
            )
        assert caught.value.code == "NARRATION_SOURCE_MISMATCH"


def test_same_inputs_same_digest_and_changed_plan_digest_changes_it() -> None:
    manifest = _two_beats()
    plan, source = _plan_and_manifest(manifest)

    def build(plan_digest: str) -> NarrationPlanV1:
        return compile_narration_plan(
            production_plan=plan,
            production_plan_digest=plan_digest,
            manifest=source,
            creative_package_digest=PACKAGE_DIGEST,
        )

    first, second = build(PLAN_DIGEST), build(PLAN_DIGEST)
    assert narration_plan_digest(first) == narration_plan_digest(second)
    assert narration_plan_digest(build("f" * 64)) != narration_plan_digest(first)


@pytest.mark.parametrize(
    "kwargs",
    [{"tts_profile_id": "narration.cloud.v1"}, {"voice_profile_id": "voice.custom.v1"}],
)
def test_unknown_profiles_are_rejected(kwargs: dict[str, str]) -> None:
    with pytest.raises(NarrationPlanError) as caught:
        _compile(_two_beats(), **kwargs)
    assert caught.value.code == "NARRATION_PROFILE_UNSUPPORTED"


def test_contract_rejects_provider_path_and_engine_fields() -> None:
    plan = _compile(_two_beats())
    document = plan.model_dump(mode="json")
    for field in (
        "provider",
        "url",
        "api_key",
        "model_path",
        "voice_file_path",
        "command",
        "rate",
        "pitch",
        "ssml",
    ):
        with pytest.raises(ValidationError):
            NarrationPlanV1.model_validate({**document, field: "x"})
        with pytest.raises(ValidationError):
            NarrationSegmentPlan.model_validate({**document["segments"][0], field: "x"})
    with pytest.raises(ValidationError):
        NarrationPlanV1.model_validate({**document, "tts_profile_id": "other"})


def test_errors_never_leak_voiceover_text() -> None:
    manifest = _manifest([("beat-1", "SECRET-VOICEOVER")], [("shot-1", "beat-1", 3.0)])
    plan, source = _plan_and_manifest(manifest)
    source["stage_results"]["script.v1"]["beats"][0]["order"] = 9  # type: ignore[index]
    with pytest.raises(NarrationPlanError) as caught:
        compile_narration_plan(
            production_plan=plan,
            production_plan_digest=PLAN_DIGEST,
            manifest=source,
            creative_package_digest=PACKAGE_DIGEST,
        )
    assert caught.value.code == "NARRATION_SOURCE_MISMATCH"
    assert "SECRET" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
