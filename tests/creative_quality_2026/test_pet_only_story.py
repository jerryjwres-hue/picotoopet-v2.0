"""PET_ONLY Video Bible compatibility: deterministic synthetic tests, no photos or GPU.

Legacy product-story schema and gates remain strict. A pet-only opt-in never manufactures
a product, and can only be selected from an explicit Goal objective.
"""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
import story_fixture_2026 as fx
from director_fixtures import V2, OllamaDouble, open_runtime, stage_outputs
from pydantic import ValidationError

from picotoopet_core.creative.director import parse_goal_directives
from picotoopet_core.creative.models import (
    CreativeBriefResult, CreativeScriptResult, CreativeStageKind,
)
from picotoopet_core.creative.profiles import (
    creative_profile_definition, pet_only_video_bible_stage,
)
from picotoopet_core.creative.video_bible import (
    KeyframeKit, PetOnlyVideoBibleDraft, VideoBible, VideoBibleDraft,
    build_keyframe_kit, derive_shot_plan, evaluate_story_storyboard,
    evaluate_video_bible, seal_bible,
)
from picotoopet_core.production.compiler import compile_production_plan

PET_GOAL = (
    "A pet-only story featuring the same family pet. Exactly 3 shots. "
    "Each shot 4 seconds. quality-first story. Natural blink, gentle breathing, "
    "then relaxed chin on paws. No products or invented merchandise."
)


def pet_script() -> dict:
    """A valid non-commercial script retaining the historical CTA beat identifier."""
    raw = deepcopy(fx.script())
    raw["title"] = "A quiet moment with Mochi"
    for beat, visual in zip(raw["beats"], (
        "Mochi closes her eyes briefly",
        "Mochi opens her eyes after a slow breath",
        "Mochi rests her chin on her paws",
    ), strict=True):
        beat["visual_intent"] = visual
        beat["voiceover"] = None
        beat["claim_source_evidence_ids"] = []
    return raw


def pet_bible() -> dict:
    """Synthetic subject-only narrative; real private Maotai images are not test data."""
    raw = deepcopy(fx.bible())
    raw["product"] = None
    raw["continuity_anchors"] = [
        "one white cat wearing the same teal scarf",
        "wooden side table with a lamp in the same room",
    ]
    raw["global_continuity_notes"] = ["Mochi keeps identical eyes, ears and coat in all shots"]
    steps = [
        (
            "Mochi rests on the wooden floor with open eyes",
            "Mochi slowly closes her eyes for a natural blink",
            "Mochi rests on the wooden floor with closed eyes",
        ),
        (
            "Mochi rests on the wooden floor with closed eyes",
            "Mochi opens her eyes softly during a slow breath",
            "Mochi rests on the wooden floor with open eyes",
        ),
        (
            "Mochi rests on the wooden floor with open eyes",
            "Mochi gently rests her chin on her front paws",
            "Mochi rests with her chin on her front paws",
        ),
    ]
    for shot, (opening, action, closing) in zip(raw["shots"], steps, strict=True):
        shot["featured"] = ["SUBJECT"]
        shot["opening_state"] = opening
        shot["visible_action"] = action
        shot["closing_state"] = closing
        shot["risk_flags"] = []
    raw["shots"][2]["handoff_to_next"] = "CUT_ON_ACTION"
    return raw


def test_pet_only_requires_an_explicit_unnegated_goal_directive() -> None:
    assert parse_goal_directives(PET_GOAL).pet_only is True
    assert parse_goal_directives(PET_GOAL).shot_count == 3
    assert parse_goal_directives(PET_GOAL).story_gate is True
    assert parse_goal_directives("Make a pet-product advert, exactly 3 shots.").pet_only is False
    assert parse_goal_directives("Do not create a pet-only story.").pet_only is False


def test_legacy_product_schema_is_unchanged_and_pet_schema_forbids_product() -> None:
    assert "product" in VideoBibleDraft.model_json_schema()["required"]
    assert "product" not in PetOnlyVideoBibleDraft.model_json_schema()["required"]
    with pytest.raises(ValidationError):
        VideoBibleDraft.model_validate(pet_bible())
    with pytest.raises(ValidationError):
        PetOnlyVideoBibleDraft.model_validate(fx.bible())
    original = VideoBibleDraft.model_validate(fx.bible())
    assert original.product is not None


def test_opt_in_video_bible_quality_seal_kit_and_compiler() -> None:
    draft = PetOnlyVideoBibleDraft.model_validate(pet_bible())
    brief = CreativeBriefResult.model_validate(fx.brief())
    script = CreativeScriptResult.model_validate(pet_script())
    findings = evaluate_video_bible(
        draft, brief=brief, script=script, evidence_ids={fx.EVIDENCE},
        required_shot_count=3, required_shot_seconds=4.0,
        story_gate=True, pet_only=True,
    )
    assert [item.code for item in findings] == []
    sealed = seal_bible(
        draft, project_key="synthetic-pet-only", source_set_digest="d" * 64,
        selected_idea_id="idea-001",
    )
    assert sealed.product is None
    assert VideoBible.model_validate(sealed.model_dump(mode="json")) == sealed
    assert evaluate_story_storyboard(sealed, product_required=False) == []
    kit = build_keyframe_kit(sealed, script, output_profile_id=brief.output_profile_id.value)
    assert KeyframeKit.model_validate(kit.model_dump(mode="json")) == kit
    assert kit.locks.product_identity_phrase is None
    assert all("charcoal tag" not in k.still_prompt for k in kit.keyframes)
    plan = compile_production_plan(
        str(uuid4()),
        {"creative_package_id": str(uuid4()), "project_key": "synthetic-pet-only",
         "quality_outcome": "PASS",
         "stage_results": {"creative_brief.v1": fx.brief(), "script.v1": pet_script(),
                           "video_bible.v1": sealed.model_dump(mode="json"),
                           "shot_plan.v1": derive_shot_plan(sealed, script)}},
        "e" * 64,
    )
    assert len(plan.tasks) == 3
    assert all("Mochi" in task.positive_prompt for task in plan.tasks)


def test_pet_only_still_rejects_story_identity_and_continuity_drift() -> None:
    corrupted = pet_bible()
    corrupted["shots"][1]["opening_state"] = "Mochi sleeps on a different sofa"
    draft = PetOnlyVideoBibleDraft.model_validate(corrupted)
    codes = {item.code for item in evaluate_story_storyboard(draft, product_required=False)}
    assert "STORY_STATE_GAP" in codes
    corrupted = pet_bible()
    corrupted["subject"]["distinguishing_marks"] = ["green scarf"]
    codes = {
        item.code for item in evaluate_story_storyboard(
            PetOnlyVideoBibleDraft.model_validate(corrupted), product_required=False
        )
    }
    assert "IDENTITY_MARK_NOT_IN_PHRASE" in codes


def test_real_creative_coordinator_selects_pet_only_stage_and_persists_package(tmp_path) -> None:
    runtime = open_runtime(tmp_path)
    try:
        job = runtime.service.create_job(
            source_result_package_ids=[runtime.result_id], creative_profile=V2,
            creative_objective=PET_GOAL, idempotency_key="synthetic-pet-only-one",
        )
        task = next(item for item in runtime.queue.list(limit=50)
                    if item.resource_tag == f"creative:{job.creative_job_id}")
        source_ref = runtime.source_ref_for(job.creative_job_id)
        outputs = stage_outputs(source_ref)
        # Synthetic existing v1 stages remain valid; only the local v2 Bible is specialized.
        brief = {**fx.brief(), "required_source_finding_refs": [source_ref]}
        double = OllamaDouble([outputs["idea"], brief, pet_script(), pet_bible()])
        summary = runtime.coordinator(double.adapter).handler(task)
        assert summary.summary["status"] == "creative_ready"
        assert len(double.requests) == 4
        assert "single-pet story" in double.requests[3]["system"]
        assert double.data(3)["director_constraints"]["pet_only"] is True
        stage = runtime.repository.get_stage(job.creative_job_id, CreativeStageKind.VIDEO_BIBLE)
        assert stage is not None
        expected_version = pet_only_video_bible_stage(
            creative_profile_definition(V2).stage(CreativeStageKind.VIDEO_BIBLE)
        ).template_version
        assert stage.template_version == expected_version
        package = runtime.service.get_package(job.creative_job_id)
        assert package is not None
        assert package.quality_outcome.value == "PASS"
        assert package.manifest["stage_results"]["video_bible.v1"]["product"] is None
        assert package.manifest["stage_results"]["keyframe_kit.v1"]["locks"]["product_identity_phrase"] is None
    finally:
        runtime.database.close()


@pytest.mark.parametrize("second_role_valid", [True, False])
def test_pet_only_arc_role_invalid_enum_retries_once_without_coercion(
    tmp_path, second_role_valid: bool
) -> None:
    """Reproduce the real arc[1].role defect using only synthetic local model replies."""
    runtime = open_runtime(tmp_path)
    try:
        job = runtime.service.create_job(
            source_result_package_ids=[runtime.result_id],
            creative_profile=V2,
            creative_objective=PET_GOAL,
            idempotency_key=f"synthetic-invalid-arc-{second_role_valid}",
        )
        task = next(
            item for item in runtime.queue.list(limit=50)
            if item.resource_tag == f"creative:{job.creative_job_id}"
        )
        source_ref = runtime.source_ref_for(job.creative_job_id)
        prior = stage_outputs(source_ref)
        brief = {**fx.brief(), "required_source_finding_refs": [source_ref]}
        invalid = pet_bible()
        invalid["arc"][1]["role"] = "ACTION"

        # Unknown role values must fail the strict enum, never become a silent alias.
        with pytest.raises(ValidationError):
            PetOnlyVideoBibleDraft.model_validate(invalid)

        responses = [
            prior["idea"], brief, pet_script(), invalid,
            pet_bible() if second_role_valid else invalid,
        ]
        double = OllamaDouble(responses)
        summary = runtime.coordinator(double.adapter).handler(task)

        # Retry one existing Job only; the targeted repair uses actual enum values.
        assert len(double.requests) == 5
        retry_prompt = double.requests[4]["user"]
        assert "arc.1.role" in retry_prompt
        assert "HOOK, DEMO, PAYOFF, CTA, BRIDGE" in retry_prompt
        assert "for exactly three beats use HOOK, DEMO, CTA" in retry_prompt
        stage = runtime.repository.get_stage(job.creative_job_id, CreativeStageKind.VIDEO_BIBLE)
        assert stage is not None
        assert stage.model_attempts == 2
        # New Goal contract : the strict pet-only template now carries the slug requirement.
        assert stage.template_version == "video-bible-pet-only-v1.0.4"
        package = runtime.service.get_package(job.creative_job_id)
        if second_role_valid:
            assert summary.summary["status"] == "creative_ready"
            assert stage.status == "Completed"
            assert package is not None
            assert package.quality_outcome.value == "PASS"
        else:
            assert summary.summary["status"] == "NeedsHuman"
            assert stage.status == "NeedsHuman"
            assert stage.result is not None
            assert stage.result["arc"][1]["role"] == "ACTION"
            assert package is None
    finally:
        runtime.database.close()
