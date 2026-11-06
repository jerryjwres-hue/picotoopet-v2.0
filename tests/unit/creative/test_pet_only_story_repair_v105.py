"""PET_ONLY director semantic contracts: safe deterministic unit tests only."""

from __future__ import annotations

from picotoopet_core.creative.director import (
    PET_ONLY_STORY_DIRECTOR_INSTRUCTIONS,
    PET_ONLY_VIDEO_BIBLE_TEMPLATE_VERSION,
)
from picotoopet_core.creative.models import CreativeStageKind
from picotoopet_core.creative.profiles import (
    creative_profile_definition,
    pet_only_video_bible_stage,
)
from picotoopet_core.creative.video_bible import BibleFinding, correction_for


def test_director_preserves_marks_and_explicit_state_handoffs() -> None:
    base = creative_profile_definition("creative.content_plan.v2").stage(
        CreativeStageKind.VIDEO_BIBLE
    )
    pet_only = pet_only_video_bible_stage(base)

    # Contract boundary      : new pet-only v2 jobs use a versioned director only.
    assert PET_ONLY_VIDEO_BIBLE_TEMPLATE_VERSION == "video-bible-pet-only-v1.0.5"
    assert pet_only.template_version == PET_ONLY_VIDEO_BIBLE_TEMPLATE_VERSION
    assert "distinguishing_marks string MUST occur verbatim" in pet_only.system_prompt
    assert "shots[0].closing_state MUST equal shots[1].opening_state" in pet_only.system_prompt
    assert "shots[1].closing_state MUST equal shots[2].opening_state" in pet_only.system_prompt
    assert "not head turns, new poses, props, or unsupported actions" in pet_only.system_prompt
    assert PET_ONLY_STORY_DIRECTOR_INSTRUCTIONS in pet_only.system_prompt


def test_semantic_retry_gives_copy_rules_without_relaxing_gates() -> None:
    findings = [
        BibleFinding("IDENTITY_MARK_NOT_IN_PHRASE", detail="cream eyebrow markings"),
        BibleFinding("STORY_NO_CHANGE"),
        BibleFinding("HANDOFF_BROKEN", shot_id="shot-1"),
        BibleFinding("STORY_STATE_GAP", shot_id="shot-2"),
    ]
    correction = correction_for(findings, pet_only=True)

    # Identity and handoff    : diagnostics are actionable, no raw source is fabricated.
    assert "EACH full distinguishing_marks entry exactly" in correction
    assert "shots[0].closing_state IDENTICAL to shots[1].opening_state" in correction
    assert "shots[1].closing_state IDENTICAL to shots[2].opening_state" in correction
    assert "only an already allowed subtle eye/emotional change" in correction
    assert "IDENTITY_MARK_NOT_IN_PHRASE" in correction
    assert "STORY_NO_CHANGE" in correction
    assert "HANDOFF_BROKEN(shot-1)" in correction
    assert "STORY_STATE_GAP(shot-2)" in correction
    assert len(correction) <= 2000


def test_legacy_nonpet_correction_is_exactly_unchanged() -> None:
    findings = [
        BibleFinding("HANDOFF_BROKEN", shot_id="shot-1", detail="copy state exactly")
    ]
    original = "Repair only these video_bible.v1 defects and keep everything else: "
    original += "HANDOFF_BROKEN(shot-1): copy state exactly"

    # Product/v1 legacy      : no extra pet instructions leak into older profiles.
    assert correction_for(findings) == original
    assert correction_for(findings, pet_only=False) == original
    assert correction_for([BibleFinding("SHOT_ORDER_INVALID")], pet_only=True) == (
        "Repair only these video_bible.v1 defects and keep everything else: "
        "SHOT_ORDER_INVALID"
    )
