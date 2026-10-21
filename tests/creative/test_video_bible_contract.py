"""Strict video_bible.v1 contract: draft schema, validation rules, sealing and derivation."""

from __future__ import annotations

import re
from copy import deepcopy
from uuid import uuid4

import pytest
from director_fixtures import (
    ANCHORS,
    EVIDENCE,
    NOTES,
    PRODUCT_PHRASE,
    SUBJECT_PHRASE,
    good_bible,
    stage_outputs,
)
from pydantic import ValidationError

from picotoopet_core.creative.models import (
    CreativeBriefResult,
    CreativeScriptResult,
    ShotPlanResult,
)
from picotoopet_core.creative.video_bible import (
    VideoBible,
    VideoBibleDraft,
    compute_bible_digest,
    correction_for,
    derive_shot_plan,
    evaluate_video_bible,
    seal_bible,
)
from picotoopet_core.production.compiler import compile_production_plan

OUT = stage_outputs("result:finding:1")
BRIEF = CreativeBriefResult.model_validate(OUT["brief"])
SCRIPT = CreativeScriptResult.model_validate(OUT["script"])
DIGEST = "d" * 64


def _codes(bible: dict) -> list[str]:
    draft = VideoBibleDraft.model_validate(bible)
    findings = evaluate_video_bible(draft, brief=BRIEF, script=SCRIPT, evidence_ids={EVIDENCE})
    return [item.code for item in findings]


def _fill_prompt_budget(bible: dict) -> None:
    bible["continuity_anchors"] = ["a" * 199] * 8
    bible["global_continuity_notes"] = ["n" * 199] * 8
    bible["subject"]["identity_phrase"] = "dog " + "d" * 230
    bible["product"]["identity_phrase"] = "tag " + "p" * 230
    shot = bible["shots"][1]
    shot.update(visible_action="v" * 400, opening_state="o" * 300, closing_state="c" * 300)


def _sealed() -> VideoBible:
    return seal_bible(
        VideoBibleDraft.model_validate(good_bible()),
        project_key="pet-tag-us", source_set_digest=DIGEST, selected_idea_id="idea-001",
    )


def test_the_good_bible_has_no_findings() -> None:
    assert _codes(good_bible()) == []


@pytest.mark.parametrize(
    "forbidden", ["reference", "reference_image_path", "workflow", "seed", "negative_prompt"]
)
def test_the_model_cannot_emit_reference_or_executor_fields(forbidden: str) -> None:
    bible = good_bible()
    bible[forbidden] = "anything"
    with pytest.raises(ValidationError):
        VideoBibleDraft.model_validate(bible)


def test_a_shot_cannot_ask_for_a_reference_image() -> None:
    bible = good_bible()
    bible["shots"][1]["uses_reference"] = True
    with pytest.raises(ValidationError):
        VideoBibleDraft.model_validate(bible)


def test_draft_json_schema_closes_the_camera_and_risk_vocabularies() -> None:
    schema = VideoBibleDraft.model_json_schema()
    movement = schema["$defs"]["CameraMovement"]["enum"]
    assert movement == [
        "STATIC", "SLOW_PUSH_IN", "SLOW_PULL_OUT", "PAN_LEFT", "PAN_RIGHT", "TRACK_SIDE"
    ]
    assert "reference" not in schema["properties"]
    assert "bible_digest" not in schema["properties"]


def test_verified_claim_without_evidence_cannot_be_constructed() -> None:
    bible = good_bible()
    bible["product"]["claims"][0]["evidence_ids"] = []
    with pytest.raises(ValidationError):
        VideoBibleDraft.model_validate(bible)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda b: b["arc"].pop(), "ARC_MISMATCH"),
        (lambda b: b["arc"][0].update(role="DEMO"), "ARC_ROLE_ORDER"),
        (lambda b: b["arc"][1].update(role="CTA"), "ARC_ROLE_ORDER"),
        (lambda b: b["subject"].update(identity_phrase="the dog"), "IDENTITY_PHRASE_TOO_VAGUE"),
        (lambda b: b["subject"].update(identity_phrase="a very friendly pet with a teal collar"),
         "IDENTITY_PHRASE_OFF_SUBJECT"),
        (lambda b: b["product"].update(identity_phrase="the product"),
         "IDENTITY_PHRASE_TOO_VAGUE"),
        (lambda b: b["product"]["claims"][0].update(evidence_ids=["reviews:key:invented"]),
         "CLAIM_UNKNOWN_EVIDENCE"),
        (lambda b: b["product"]["claims"][0].update(verified=False, evidence_ids=[]),
         "CLAIM_UNVERIFIED_IN_VOICEOVER"),
        (lambda b: b["shots"][2].update(order=9), "SHOT_ORDER_INVALID"),
        (lambda b: b["shots"][0].update(beat_id="beat-404"), "SHOT_UNKNOWN_BEAT"),
        (lambda b: b["shots"][0].update(beat_id="beat-003"), "SHOT_BEAT_ORDER"),
        (lambda b: b["shots"].pop(), "SCRIPT_BEAT_NOT_COVERED"),
        (lambda b: [s.update(duration_seconds=2.0) for s in b["shots"]], "TIMELINE_MISMATCH"),
        (lambda b: [s.update(featured=["SUBJECT"]) for s in b["shots"]], "PRODUCT_NEVER_FEATURED"),
        (lambda b: b["shots"][0].update(scene_id="roof"), "SCENE_UNKNOWN"),
        (lambda b: b["camera_rules"].update(allowed_movements=["STATIC"]),
         "CAMERA_RULE_VIOLATION"),
        (lambda b: b["shots"][0].update(duration_seconds=8.0), "SHOT_DURATION_UNRENDERABLE"),
        (lambda b: b["shots"][0].update(duration_seconds=1.0), "SHOT_DURATION_TOO_SHORT"),
        (lambda b: b["shots"][0].update(visible_action="Biscuit sits then jumps"),
         "ACTION_MULTI_STEP"),
        (lambda b: b["shots"][0].update(visible_action="Biscuit sits; Biscuit jumps"),
         "ACTION_MULTI_STEP"),
        (lambda b: b["shots"][1].update(risk_flags=["TEXT_IN_FRAME"]),
         "TEXT_IN_FRAME_CONTRADICTION"),
        (lambda b: b["shots"][0].update(handoff_to_next="CONTINUOUS"), "HANDOFF_BROKEN"),
        (lambda b: b["scenes"][0].update(environment_phrase="cinematic 8K masterpiece porch"),
         "QUALITY_ADJECTIVE_SPAM"),
        (lambda b: _fill_prompt_budget(b), "PROMPT_TOO_LONG"),
    ],
)
def test_each_rule_fires_on_exactly_its_defect(mutate, code: str) -> None:  # type: ignore[no-untyped-def]
    bible = deepcopy(good_bible())
    mutate(bible)
    assert code in _codes(bible)


def test_continuous_handoff_passes_when_states_match_word_for_word() -> None:
    bible = good_bible()
    bible["shots"][0]["handoff_to_next"] = "CONTINUOUS"
    bible["shots"][1]["opening_state"] = "  Biscuit   SITS facing camera "
    assert "HANDOFF_BROKEN" not in _codes(bible)


@pytest.mark.parametrize(
    "text",
    ["a dog like assets/biscuit.png", "see C:\\Users\\a\\dog.jpg", "clip.mp4 style", "~/refs/dog/"],
)
def test_path_like_text_is_rejected_not_retried(text: str) -> None:
    bible = good_bible()
    bible["scenes"][0]["palette"] = [text]
    draft = VideoBibleDraft.model_validate(bible)
    findings = evaluate_video_bible(draft, brief=BRIEF, script=SCRIPT, evidence_ids={EVIDENCE})
    assert any(item.code == "BIBLE_PATH_LIKE" and item.reject for item in findings)


def test_correction_text_is_bounded_and_names_the_defects() -> None:
    bible = good_bible()
    bible["shots"][0]["duration_seconds"] = 8.0
    draft = VideoBibleDraft.model_validate(bible)
    findings = evaluate_video_bible(draft, brief=BRIEF, script=SCRIPT, evidence_ids={EVIDENCE})
    text = correction_for(findings)
    assert "SHOT_DURATION_UNRENDERABLE(shot-001)" in text and len(text) < 2000


def test_sealing_binds_source_and_idea_and_is_deterministic() -> None:
    first, second = _sealed(), _sealed()
    assert first == second and first.bible_digest == second.bible_digest
    assert first.source_set_digest == DIGEST and first.selected_idea_id == "idea-001"
    assert first.goal_id == "pet-tag-us" and re.fullmatch(r"vb-[0-9a-f]{16}", first.bible_id)
    assert first.bible_digest == compute_bible_digest(first.model_dump(mode="json"))
    other = seal_bible(
        VideoBibleDraft.model_validate(good_bible()),
        project_key="pet-tag-us", source_set_digest="e" * 64, selected_idea_id="idea-001",
    )
    assert other.bible_digest != first.bible_digest


def test_tampering_with_a_sealed_bible_is_detected() -> None:
    payload = _sealed().model_dump(mode="json")
    payload["subject"]["coat_or_appearance"] = "black coat"
    with pytest.raises(ValidationError, match="bible_digest"):
        VideoBible.model_validate(payload)
    frozen = _sealed()
    with pytest.raises(ValidationError):
        frozen.bible_id = "other"  # type: ignore[misc]


def test_derived_shot_plan_is_a_valid_existing_shot_plan_with_no_new_fields() -> None:
    bible = _sealed()
    raw = derive_shot_plan(bible, SCRIPT)
    plan = ShotPlanResult.model_validate(raw)
    assert [s.shot_id for s in plan.shots] == [s.shot_id for s in bible.shots]
    assert {s.render_intent.value for s in plan.shots} == {"GENERATIVE_VIDEO"}
    for shot, source in zip(plan.shots, bible.shots, strict=True):
        if "SUBJECT" in [f.value for f in source.featured]:
            assert SUBJECT_PHRASE in shot.subject
        if "PRODUCT" in [f.value for f in source.featured]:
            assert PRODUCT_PHRASE in shot.subject
        assert set(ANCHORS) | set(NOTES) <= set(shot.continuity_keys)
        assert bible.bible_digest[:16] in shot.production_notes
    evidence = {s.shot_id: s.source_evidence_ids for s in plan.shots}
    assert evidence["shot-002"] == evidence["shot-003"] == [EVIDENCE]
    assert evidence["shot-001"] == []


def test_derived_plan_compiles_into_an_executable_production_plan() -> None:
    bible = _sealed()
    outputs = stage_outputs("result:finding:1")
    manifest = {
        "creative_package_id": str(uuid4()), "project_key": "pet-tag-us",
        "quality_outcome": "PASS",
        "stage_results": {
            "creative_brief.v1": outputs["brief"], "script.v1": outputs["script"],
            "video_bible.v1": bible.model_dump(mode="json"),
            "shot_plan.v1": derive_shot_plan(bible, SCRIPT),
        },
    }
    plan = compile_production_plan(str(uuid4()), manifest, "e" * 64)
    assert [t.execution_disposition.value for t in plan.tasks] == ["Executable"] * 4
    assert [t.frame_count for t in plan.tasks] == [97] * 4
    assert {t.trusted_input_asset_ref for t in plan.tasks} == {None}
    for task in plan.tasks:
        assert "wan22-shot-prompt-v1.1.0" not in task.positive_prompt  # brief has no notes
        for anchor in ANCHORS:
            assert anchor in task.positive_prompt
        assert SUBJECT_PHRASE in task.positive_prompt
