from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from picotoopet_core.postproduction.captions_overlay import (
    CAPTION_STYLE_PROFILE_ID,
    FONT_PROFILE_ID,
    OVERLAY_STYLE_PROFILE_ID,
    CaptionOverlayPlanError,
    CaptionOverlayPlanV1,
    CaptionCueV1,
    TextOverlayCueV1,
    caption_overlay_plan_digest,
    compile_caption_overlay_plan,
)
from picotoopet_core.production.models import ProductionPlan, ProductionTaskPlan

PACKAGE_DIGEST = "b" * 64


def _manifest(
    beats: list[tuple[str, str | None, str | None]],
    shots: list[tuple[str, str, int, str, str | None]],
) -> dict[str, object]:
    # ── Script durations mirror shot mapping; C005 task ms stays authoritative. ──
    beat_duration_ms = {beat_id: 0 for beat_id, _, _ in beats}
    for _, beat_id, duration_ms, _, _ in shots:
        if beat_id in beat_duration_ms:
            beat_duration_ms[beat_id] += duration_ms
    target_ms = sum(duration_ms for _, _, duration_ms, _, _ in shots)
    return {
        "schema_version": "1.0",
        "creative_package_id": str(uuid4()),
        "stage_results": {
            "script.v1": {
                "schema_version": "1.0",
                "creative_profile": "creative.content_plan.v1",
                "script_id": "script-001",
                "title": "Caption overlay fixture",
                "target_duration_seconds": target_ms / 1000,
                "beats": [
                    {
                        "beat_id": beat_id,
                        "order": index,
                        "duration_seconds": max(beat_duration_ms[beat_id], 1) / 1000,
                        "voiceover": voiceover,
                        "on_screen_text": on_screen_text,
                        "visual_intent": "Existing rendered timeline",
                        "claim_source_evidence_ids": [],
                        "unsupported_claim": False,
                    }
                    for index, (beat_id, voiceover, on_screen_text) in enumerate(beats, start=1)
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
                        "duration_seconds": duration_ms / 1000,
                        "subject": "pet",
                        "environment": "home",
                        "action": "moves",
                        "framing": "medium",
                        "lighting_style": "soft",
                        "continuity_keys": [],
                        "required_facts": [],
                        "source_evidence_ids": [],
                        "text_reference": text_reference,
                        "production_notes": "renderer-neutral",
                        "render_intent": render_intent,
                    }
                    for index, (
                        shot_id,
                        beat_id,
                        duration_ms,
                        render_intent,
                        text_reference,
                    ) in enumerate(shots, start=1)
                ],
                "warnings": [],
                "needs_deep_ai": False,
                "needs_human": False,
            },
        },
    }


def _production_plan(manifest: dict[str, object]) -> ProductionPlan:
    shots = manifest["stage_results"]["shot_plan.v1"]["shots"]  # type: ignore[index]
    tasks = [
        ProductionTaskPlan(
            production_task_id=str(uuid4()),
            shot_id=shot["shot_id"],
            order=index,
            render_intent=shot["render_intent"],
            execution_disposition="NeedsHuman",
            workflow_id=None,
            positive_prompt="bounded fixture",
            negative_prompt_policy_id="wan22.safe-negative.v1",
            seed=index,
            width=832,
            height=480,
            fps=24,
            frame_count=73,
            target_duration_ms=round(float(shot["duration_seconds"]) * 1000),
            trusted_input_asset_ref=None,
        )
        for index, shot in enumerate(shots, start=1)
    ]
    return ProductionPlan(
        schema_version="1.0",
        production_profile="production.comfyui.v1",
        production_job_id=str(uuid4()),
        creative_package_id=manifest["creative_package_id"],
        creative_package_digest=PACKAGE_DIGEST,
        project_key="pet-video",
        output_profile_id="video.landscape.v1",
        target_runtime_ms=sum(task.target_duration_ms for task in tasks),
        tasks=tasks,
    )


def _production_digest(plan: ProductionPlan) -> str:
    # ── C008A validates the exact durable C005 plan digest before using timing. ──
    encoded = json.dumps(
        plan.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _compile(
    manifest: dict[str, object],
    *,
    production_plan: ProductionPlan | None = None,
    **kwargs: str,
) -> CaptionOverlayPlanV1:
    plan = production_plan or _production_plan(manifest)
    return compile_caption_overlay_plan(
        production_plan=plan,
        production_plan_digest=kwargs.pop("production_plan_digest", _production_digest(plan)),
        manifest=manifest,
        creative_package_digest=kwargs.pop("creative_package_digest", PACKAGE_DIGEST),
        **kwargs,
    )


def _one_shot(
    *,
    voiceover: str | None = None,
    on_screen_text: str | None = None,
    render_intent: str = "GENERATIVE_VIDEO",
    text_reference: str | None = None,
) -> dict[str, object]:
    return _manifest(
        [("beat-1", voiceover, on_screen_text)],
        [("shot-1", "beat-1", 3000, render_intent, text_reference)],
    )


def test_no_on_screen_text_is_valid_empty_plan() -> None:
    plan = _compile(_one_shot(voiceover="Narration only."))
    assert plan.captions == []
    assert plan.overlays == []
    assert plan.captions_required is False
    assert plan.overlays_required is False


def test_one_overlay_gets_exact_production_window_and_profiles() -> None:
    plan = _compile(_one_shot(on_screen_text="Dry faster"))
    assert len(plan.overlays) == 1
    cue = plan.overlays[0]
    assert (cue.beat_id, cue.start_ms, cue.end_ms) == ("beat-1", 0, 3000)
    assert cue.text == "Dry faster"
    assert cue.cue_kind == "overlay"
    assert plan.caption_style_profile_id == CAPTION_STYLE_PROFILE_ID
    assert plan.overlay_style_profile_id == OVERLAY_STYLE_PROFILE_ID
    assert plan.font_profile_id == FONT_PROFILE_ID
    assert plan.overlays_required is True


def test_multi_shot_beat_spans_full_window() -> None:
    manifest = _manifest(
        [("beat-1", None, "One beat")],
        [
            ("shot-1", "beat-1", 1200, "GENERATIVE_VIDEO", None),
            ("shot-2", "beat-1", 1800, "IMAGE_TO_VIDEO", None),
        ],
    )
    cue = _compile(manifest).overlays[0]
    assert (cue.start_ms, cue.end_ms) == (0, 3000)


def test_multi_beat_timing_accumulates_from_tasks() -> None:
    manifest = _manifest(
        [("beat-1", None, "First"), ("beat-2", None, "Second")],
        [
            ("shot-1", "beat-1", 1500, "GENERATIVE_VIDEO", None),
            ("shot-2", "beat-2", 2500, "GENERATIVE_VIDEO", None),
        ],
    )
    plan = _compile(manifest)
    assert [(cue.beat_id, cue.start_ms, cue.end_ms) for cue in plan.overlays] == [
        ("beat-1", 0, 1500),
        ("beat-2", 1500, 4000),
    ]
    assert plan.target_runtime_ms == 4000


def test_on_screen_text_never_becomes_caption() -> None:
    plan = _compile(_one_shot(on_screen_text="Authored overlay"))
    assert [cue.text for cue in plan.overlays] == ["Authored overlay"]
    assert plan.captions == []


def test_voiceover_never_becomes_overlay_or_caption() -> None:
    plan = _compile(_one_shot(voiceover="Spoken words only."))
    assert plan.overlays == []
    assert plan.captions == []


def test_text_reference_alone_produces_no_postproduction_text() -> None:
    plan = _compile(_one_shot(text_reference="TEXT_CARD renderer reference"))
    assert plan.overlays == []
    assert plan.captions == []


def test_text_card_with_on_screen_text_is_ambiguous() -> None:
    with pytest.raises(CaptionOverlayPlanError) as caught:
        _compile(_one_shot(on_screen_text="Do not duplicate", render_intent="TEXT_CARD"))
    assert caught.value.code == "TEXT_OVERLAY_TEXT_CARD_AMBIGUOUS"


def test_text_card_without_overlay_does_not_false_positive_for_future_caption_semantics() -> None:
    plan = _compile(_one_shot(voiceover="Future caption source.", render_intent="TEXT_CARD"))
    assert plan.overlays == []
    assert plan.captions == []
    assert plan.captions_required is False


def test_unknown_shot_identity_is_rejected() -> None:
    manifest = _one_shot(on_screen_text="Visible")
    plan = _production_plan(manifest)
    broken = deepcopy(manifest)
    broken["stage_results"]["shot_plan.v1"]["shots"][0]["shot_id"] = "shot-x"  # type: ignore[index]
    broken["creative_package_id"] = plan.creative_package_id
    with pytest.raises(CaptionOverlayPlanError) as caught:
        _compile(broken, production_plan=plan)
    assert caught.value.code == "TEXT_PRESENTATION_TIMELINE_AMBIGUOUS"


def test_unknown_beat_mapping_is_rejected() -> None:
    manifest = _one_shot(on_screen_text="Visible")
    plan = _production_plan(manifest)
    broken = deepcopy(manifest)
    broken["stage_results"]["shot_plan.v1"]["shots"][0]["beat_id"] = "beat-x"  # type: ignore[index]
    broken["creative_package_id"] = plan.creative_package_id
    with pytest.raises(CaptionOverlayPlanError) as caught:
        _compile(broken, production_plan=plan)
    assert caught.value.code == "TEXT_PRESENTATION_TIMELINE_AMBIGUOUS"


def test_reopened_noncontiguous_beat_is_rejected() -> None:
    manifest = _manifest(
        [("beat-1", None, "One"), ("beat-2", None, "Two")],
        [
            ("shot-1", "beat-1", 1000, "GENERATIVE_VIDEO", None),
            ("shot-2", "beat-2", 1000, "GENERATIVE_VIDEO", None),
            ("shot-3", "beat-1", 1000, "GENERATIVE_VIDEO", None),
        ],
    )
    with pytest.raises(CaptionOverlayPlanError) as caught:
        _compile(manifest)
    assert caught.value.code == "TEXT_PRESENTATION_TIMELINE_AMBIGUOUS"


def test_task_order_and_runtime_mismatch_are_rejected() -> None:
    manifest = _manifest(
        [("beat-1", None, "One"), ("beat-2", None, "Two")],
        [
            ("shot-1", "beat-1", 1000, "GENERATIVE_VIDEO", None),
            ("shot-2", "beat-2", 1000, "GENERATIVE_VIDEO", None),
        ],
    )
    plan = _production_plan(manifest)
    for broken in (
        plan.model_copy(update={"tasks": [plan.tasks[1], plan.tasks[0]]}),
        plan.model_copy(update={"target_runtime_ms": plan.target_runtime_ms + 1}),
    ):
        with pytest.raises(CaptionOverlayPlanError) as caught:
            _compile(
                manifest,
                production_plan=broken,
                production_plan_digest=_production_digest(broken),
            )
        assert caught.value.code == "TEXT_PRESENTATION_TIMELINE_AMBIGUOUS"


def test_source_identity_and_digests_are_bound() -> None:
    manifest = _one_shot(on_screen_text="Visible")
    plan = _production_plan(manifest)

    wrong_id = deepcopy(manifest)
    wrong_id["creative_package_id"] = str(uuid4())
    with pytest.raises(CaptionOverlayPlanError) as caught_id:
        _compile(wrong_id, production_plan=plan)
    assert caught_id.value.code == "TEXT_PRESENTATION_SOURCE_MISMATCH"

    with pytest.raises(CaptionOverlayPlanError) as caught_creative:
        _compile(manifest, production_plan=plan, creative_package_digest="e" * 64)
    assert caught_creative.value.code == "TEXT_PRESENTATION_SOURCE_MISMATCH"

    with pytest.raises(CaptionOverlayPlanError) as caught_plan:
        _compile(manifest, production_plan=plan, production_plan_digest="f" * 64)
    assert caught_plan.value.code == "TEXT_PRESENTATION_SOURCE_MISMATCH"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"caption_style_profile_id": "caption.custom.v1"},
        {"overlay_style_profile_id": "overlay.custom.v1"},
        {"font_profile_id": "font.custom.v1"},
    ],
)
def test_unknown_style_or_font_profile_is_rejected(kwargs: dict[str, str]) -> None:
    with pytest.raises(CaptionOverlayPlanError) as caught:
        _compile(_one_shot(on_screen_text="Visible"), **kwargs)
    assert caught.value.code == "TEXT_PRESENTATION_PROFILE_UNSUPPORTED"


def test_contract_rejects_renderer_authority_fields() -> None:
    plan = _compile(_one_shot(on_screen_text="Visible"))
    plan_document = plan.model_dump(mode="json")
    cue_document = plan_document["overlays"][0]
    forbidden = (
        "provider",
        "model",
        "path",
        "font_path",
        "filter",
        "command",
        "url",
        "executable",
        "width",
        "height",
        "fps",
    )
    for field in forbidden:
        with pytest.raises(ValidationError):
            CaptionOverlayPlanV1.model_validate({**plan_document, field: "x"})
        with pytest.raises(ValidationError):
            TextOverlayCueV1.model_validate({**cue_document, field: "x"})


def test_caption_contract_is_strict_but_not_populated_by_c008a() -> None:
    cue = CaptionCueV1(
        cue_id="caption-001",
        beat_id="beat-1",
        order=1,
        text="Trusted future transcript",
        text_sha256=hashlib.sha256(b"Trusted future transcript").hexdigest(),
        start_ms=0,
        end_ms=1000,
    )
    assert cue.cue_kind == "caption"


def test_same_inputs_produce_same_plan_and_digest() -> None:
    manifest = _one_shot(on_screen_text="Stable")
    plan = _production_plan(manifest)
    first = _compile(manifest, production_plan=plan)
    second = _compile(manifest, production_plan=plan)
    assert first == second
    assert caption_overlay_plan_digest(first) == caption_overlay_plan_digest(second)


def test_changed_production_plan_digest_changes_plan_digest_when_bound_to_new_plan() -> None:
    manifest = _one_shot(on_screen_text="Stable")
    plan = _production_plan(manifest)
    first = _compile(manifest, production_plan=plan)

    changed = plan.model_copy(update={"production_job_id": str(uuid4())})
    second = _compile(
        manifest,
        production_plan=changed,
        production_plan_digest=_production_digest(changed),
    )
    assert first.production_plan_digest != second.production_plan_digest
    assert caption_overlay_plan_digest(first) != caption_overlay_plan_digest(second)


def test_errors_never_leak_authored_text() -> None:
    secret = "SECRET-OVERLAY-CONTENT"
    manifest = _one_shot(on_screen_text=secret)
    plan = _production_plan(manifest)
    broken = deepcopy(manifest)
    broken["stage_results"]["script.v1"]["beats"][0]["order"] = 9  # type: ignore[index]
    broken["creative_package_id"] = plan.creative_package_id
    with pytest.raises(CaptionOverlayPlanError) as caught:
        _compile(broken, production_plan=plan)
    assert caught.value.code == "TEXT_PRESENTATION_SOURCE_MISMATCH"
    assert secret not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_required_overlay_cannot_silently_disappear() -> None:
    manifest = _manifest(
        [("beat-1", None, "Required"), ("beat-2", None, None)],
        [
            ("shot-1", "beat-1", 1000, "GENERATIVE_VIDEO", None),
            ("shot-2", "beat-2", 1000, "GENERATIVE_VIDEO", None),
        ],
    )
    plan = _production_plan(manifest)
    broken = deepcopy(manifest)
    broken["stage_results"]["shot_plan.v1"]["shots"][0]["beat_id"] = "beat-2"  # type: ignore[index]
    broken["creative_package_id"] = plan.creative_package_id
    with pytest.raises(CaptionOverlayPlanError) as caught:
        _compile(broken, production_plan=plan)
    assert caught.value.code == "TEXT_PRESENTATION_TIMELINE_AMBIGUOUS"


def test_optional_caption_absence_is_non_fatal() -> None:
    plan = _compile(_one_shot(voiceover="Narration exists, trusted transcript does not."))
    assert plan.captions_required is False
    assert plan.captions == []


def test_outer_whitespace_is_trimmed_but_authored_interior_whitespace_is_preserved() -> None:
    plan = _compile(_one_shot(on_screen_text="  Line one  \nLine two  "))
    assert plan.overlays[0].text == "Line one  \nLine two"
