"""Story gate and keyframe kit: native, deterministic, text-only (no model, no picture, no GPU)."""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import pytest
import story_fixture_2026 as fx
from pydantic import ValidationError

from picotoopet_core.creative.director import STORY_DIRECTOR_INSTRUCTIONS
from picotoopet_core.creative.models import (
    CreativeBriefResult,
    CreativeScriptResult,
    ShotPlanResult,
)
from picotoopet_core.creative.video_bible import (
    CORE_ENFORCEMENT_REQUIRED,
    KeyframeGateOutcome,
    KeyframeKit,
    KeyframeKitError,
    KeyframeSubmission,
    VideoBible,
    VideoBibleDraft,
    build_keyframe_kit,
    derive_shot_plan,
    evaluate_keyframe_submissions,
    evaluate_story_storyboard,
    evaluate_video_bible,
    seal_bible,
)
from picotoopet_core.production.compiler import compile_production_plan

BRIEF = CreativeBriefResult.model_validate(fx.brief())
SCRIPT = CreativeScriptResult.model_validate(fx.script())
PROFILE = BRIEF.output_profile_id.value


def _draft(data: dict | None = None) -> VideoBibleDraft:
    return VideoBibleDraft.model_validate(data or fx.bible())


def _sealed() -> VideoBible:
    return seal_bible(
        _draft(), project_key="pet-tag-us", source_set_digest="d" * 64, selected_idea_id="idea-001"
    )


def _codes(data: dict, *, gate: bool = True) -> list[str]:
    findings = evaluate_video_bible(
        _draft(data), brief=BRIEF, script=SCRIPT, evidence_ids={fx.EVIDENCE},
        required_shot_count=3, required_shot_seconds=4.0, story_gate=gate,
    )
    return [item.code for item in findings]


def test_canonical_story_passes_every_existing_and_story_gate() -> None:
    assert _codes(fx.bible()) == []


def test_canonical_story_round_trips_through_strict_json_and_derives_a_valid_plan() -> None:
    reloaded = VideoBibleDraft.model_validate_json(json.dumps(fx.bible()))
    assert reloaded == _draft()
    sealed = _sealed()
    plan = ShotPlanResult.model_validate(derive_shot_plan(sealed, SCRIPT))
    assert [s.render_intent.value for s in plan.shots] == ["GENERATIVE_VIDEO"] * 3
    for shot in plan.shots:
        assert fx.SUBJECT_PHRASE in shot.subject
        assert "lamp" in " ".join(shot.continuity_keys)
    envs = {s.environment for s in plan.shots}
    lights = {s.lighting_style for s in plan.shots}
    assert len(envs) == len(lights) == 1  # fixed scene layout and lighting in every shot


def test_derived_plan_compiles_with_the_unchanged_compiler() -> None:
    sealed = _sealed()
    manifest = {
        "creative_package_id": str(uuid4()), "project_key": "pet-tag-us",
        "quality_outcome": "PASS",
        "stage_results": {
            "creative_brief.v1": fx.brief(), "script.v1": fx.script(),
            "video_bible.v1": sealed.model_dump(mode="json"),
            "shot_plan.v1": derive_shot_plan(sealed, SCRIPT),
        },
    }
    plan = compile_production_plan(str(uuid4()), manifest, "e" * 64)
    assert [t.execution_disposition.value for t in plan.tasks] == ["Executable"] * 3
    assert {t.trusted_input_asset_ref for t in plan.tasks} == {None}
    for task in plan.tasks:
        assert fx.SUBJECT_PHRASE in task.positive_prompt


def _set_shot(index: int, **changes):
    def mutate(b: dict) -> None:
        b["shots"][index].update(changes)
    return mutate


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda b: b["subject"].update(distinguishing_marks=[]), "IDENTITY_MARKS_MISSING"),
        (lambda b: b["subject"].update(distinguishing_marks=["green scarf"]),
         "IDENTITY_MARK_NOT_IN_PHRASE"),
        (_set_shot(1, visible_action="a hand clips the tag onto the green scarf under "
                   "Mochi's chin"), "IDENTITY_COLOUR_DRIFT"),
        (_set_shot(0, visible_action="another white cat watches Mochi tap the tag"),
         "SUBJECT_MULTIPLIED"),
        (_set_shot(2, visible_action="the lamp floating beside Mochi as she walks left to "
                   "right"), "FLOATING_OBJECT_WORDING"),
        (_set_shot(1, visible_action="a hand presents the charcoal tag",
                   opening_state="Mochi waits", closing_state="the charcoal tag is displayed"),
         "PRODUCT_CONTACT_MISSING"),
        (_set_shot(1, scene_id="living_room2"), "STORY_SCENE_SPLIT"),
        (lambda b: b["camera_rules"].update(screen_direction="NONE"),
         "STORY_SCREEN_DIRECTION_UNSET"),
        (_set_shot(0, handoff_to_next="CUT_ON_ACTION"), "STORY_HANDOFF_NOT_CONTINUOUS"),
        (_set_shot(2, camera_framing="close-up", camera_movement="SLOW_PUSH_IN"),
         "STORY_CAMERA_NO_PROGRESSION"),
        (_set_shot(1, featured=["SUBJECT"]), "STORY_PRODUCT_DISAPPEARS"),
        (_set_shot(2, featured=["SUBJECT"]), "STORY_PAYOFF_MISSING"),
    ],
)
def test_story_gate_rejects_the_failure_patterns_of_the_rejected_film(mutate, code) -> None:
    data = fx.bible()
    if code == "STORY_SCENE_SPLIT":
        data["scenes"].append({**data["scenes"][0], "scene_id": "living_room2"})
    mutate(data)
    assert code in _codes(data)


def test_scene_lighting_must_not_vary_and_the_story_must_change_state() -> None:
    data = fx.bible()
    data["scenes"].append({**data["scenes"][0], "scene_id": "other",
                           "lighting_phrase": "cold blue night light"})
    assert "STORY_LIGHTING_VARIES" in _codes(data)
    data = fx.bible()
    data["shots"][2]["closing_state"] = data["shots"][0]["opening_state"]
    assert "STORY_NO_CHANGE" in _codes(data)


def test_broken_state_handoff_is_a_story_gap() -> None:
    data = fx.bible()
    data["shots"][1]["opening_state"] = "Mochi sleeps on the sofa"
    assert "STORY_STATE_GAP" in _codes(data)


def test_story_gate_is_opt_in_and_legacy_gate_unchanged() -> None:
    data = fx.bible()
    data["scenes"].append({**data["scenes"][0], "scene_id": "park"})
    data["shots"][2]["scene_id"] = "park"
    assert "STORY_SCENE_SPLIT" not in _codes(data, gate=False)
    assert "STORY_SCENE_SPLIT" in [i.code for i in evaluate_story_storyboard(_draft(data))]


def test_legacy_schema_and_director_instructions_are_byte_identical() -> None:
    schema = json.dumps(VideoBibleDraft.model_json_schema(), sort_keys=True)
    assert hashlib.sha256(schema.encode()).hexdigest() == (
        "d490c34c601247c6494ee83762e94136929ea0e60d5f9b5b35030f3710c01b0e"
    )
    assert hashlib.sha256(STORY_DIRECTOR_INSTRUCTIONS.encode()).hexdigest() == (
        "9fd4a7f54c29f3d9000ce7b9e5adbd51c2a0ed2b80d98cff9411a84090533751"
    )


# ── Keyframe kit ───────────────────────────────────────────────────────────────────────


def _kit() -> KeyframeKit:
    return build_keyframe_kit(_sealed(), SCRIPT, output_profile_id=PROFILE)


def _subs(kit: KeyframeKit, **override) -> list[KeyframeSubmission]:
    return [
        KeyframeSubmission(
            keyframe_id=item.keyframe_id, locks_digest=kit.locks.locks_digest,
            width=fx.WIDTH, height=fx.HEIGHT, human_approved=True,
            image_sha256=f"{index:064x}", **override,
        )
        for index, item in enumerate(kit.keyframes, start=1)
    ]


def test_kit_has_three_pending_approval_stills_sharing_identical_locks() -> None:
    kit = _kit()
    assert [k.shot_id for k in kit.keyframes] == ["shot-001", "shot-002", "shot-003"]
    assert {k.approval_status.value for k in kit.keyframes} == {"PENDING_HUMAN_REVIEW"}
    for frame in kit.keyframes:
        assert fx.SUBJECT_PHRASE in frame.still_prompt
        assert kit.locks.lighting_phrase in frame.still_prompt
        assert any("nothing floats" in item for item in frame.review_checklist)
    assert kit.locks.aspect_ratio == "16:9"
    assert kit.bible_digest == _sealed().bible_digest
    assert KeyframeKit.model_validate(kit.model_dump(mode="json")) == kit


def test_manifest_is_an_untrusted_proposal_without_paths_or_digests() -> None:
    kit = _kit()
    dumped = json.dumps(kit.model_dump(mode="json"))
    assert {p.trust_state for p in kit.reference_manifest_proposal} == {"UNTRUSTED_PROPOSAL"}
    assert ".png" not in dumped and "trusted_local_assets" in " ".join(CORE_ENFORCEMENT_REQUIRED)
    assert kit.core_enforcement_required == list(CORE_ENFORCEMENT_REQUIRED)


def test_tampered_kit_is_rejected() -> None:
    raw = _kit().model_dump(mode="json")
    raw["locks"]["lighting_phrase"] = "something else"
    with pytest.raises(ValidationError):
        KeyframeKit.model_validate(raw)


def test_kit_refuses_a_story_that_fails_the_gate_or_has_wrong_shot_count() -> None:
    data = fx.bible()
    data["shots"][1]["visible_action"] = "a hand clips the tag onto the green scarf"
    bad = seal_bible(_draft(data), project_key="p", source_set_digest="d" * 64,
                     selected_idea_id="idea-001")
    with pytest.raises(KeyframeKitError, match="IDENTITY_COLOUR_DRIFT"):
        build_keyframe_kit(bad, SCRIPT, output_profile_id=PROFILE)


def test_consistent_approved_stills_only_reach_awaiting_core_never_send() -> None:
    decision = evaluate_keyframe_submissions(_kit(), _subs(_kit()))
    assert decision.outcome is KeyframeGateOutcome.AWAITING_CORE_PROVENANCE
    assert decision.send_allowed is False


@pytest.mark.parametrize(
    ("index", "update", "reason"),
    [
        (1, {"locks_digest": "f" * 64}, "KEYFRAME_CONDITIONS_DIFFER"),
        (2, {"width": 1080}, "KEYFRAME_ASPECT_DIFFERS"),
        (0, {"human_approved": False}, "KEYFRAME_NOT_HUMAN_APPROVED"),
        (0, {"image_sha256": None}, "KEYFRAME_IMAGE_DIGEST_MISSING"),
        (1, {"image_sha256": f"{1:064x}"}, "KEYFRAMES_IDENTICAL"),
        (0, {"keyframe_id": "kf-other"}, "KEYFRAME_UNKNOWN_ID"),
    ],
)
def test_inconsistent_keyframe_conditions_fail_closed_with_no_send(index, update, reason) -> None:
    kit = _kit()
    subs = _subs(kit)
    subs[index] = subs[index].model_copy(update=update)
    decision = evaluate_keyframe_submissions(kit, subs)
    assert decision.outcome is KeyframeGateOutcome.NO_SEND
    assert any(item.startswith(reason) for item in decision.reasons)
    assert decision.send_allowed is False


def test_a_missing_keyframe_is_no_send() -> None:
    kit = _kit()
    decision = evaluate_keyframe_submissions(kit, _subs(kit)[:2])
    assert decision.outcome is KeyframeGateOutcome.NO_SEND
    assert "KEYFRAME_MISSING" in decision.reasons


def test_submission_cannot_carry_trust_or_paths() -> None:
    with pytest.raises(ValidationError):
        KeyframeSubmission.model_validate({
            "keyframe_id": "kf-shot-001", "locks_digest": "a" * 64, "width": 1, "height": 1,
            "path": "C:/x.png", "trusted": True,
        })
