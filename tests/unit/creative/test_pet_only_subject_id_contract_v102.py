"""Contract regression for pet-only Video Bible subject ID syntax."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from picotoopet_core.creative.director import (
    PET_ONLY_STORY_DIRECTOR_INSTRUCTIONS,
    PET_ONLY_VIDEO_BIBLE_TEMPLATE_VERSION,
    VIDEO_BIBLE_TEMPLATE_VERSION,
)
from picotoopet_core.creative.models import CreativeStageKind
from picotoopet_core.creative.profiles import (
    creative_profile_definition,
    pet_only_video_bible_stage,
)
from picotoopet_core.creative.video_bible import (
    PetOnlyVideoBibleDraft,
    SubjectIdentity,
)


def _subject(subject_id: str) -> SubjectIdentity:
    # Synthetic fixture only : no actual owner evidence or reference image.
    return SubjectIdentity(
        subject_id=subject_id,
        kind="PET",
        species="dog",
        breed_or_type="Alaskan Malamute",
        coat_or_appearance="black, brown, tan and cream",
        distinguishing_marks=["irregular pink-and-black nose markings"],
        identity_phrase="adult Alaskan Malamute with black, brown, tan and cream fur",
    )


@pytest.mark.parametrize("subject_id", ["maotai", "pet_001", "dog.v1", "pet-02"])
def test_pet_subject_id_accepts_ascii_slug(subject_id: str) -> None:
    assert _subject(subject_id).subject_id == subject_id


@pytest.mark.parametrize("subject_id", ["pet:maotai", "Maotai Dog", "茅台", "pet/id"])
def test_pet_subject_id_rejects_non_slug(subject_id: str) -> None:
    with pytest.raises(ValidationError):
        _subject(subject_id)


def test_pet_only_model_prompt_contract_matches_schema() -> None:
    base = creative_profile_definition("creative.content_plan.v2").stage(
        CreativeStageKind.VIDEO_BIBLE
    )
    pet_only = pet_only_video_bible_stage(base)

    # Versioned model contract : new Goals use v1.0.2; legacy profile is untouched.
    assert base.template_version == VIDEO_BIBLE_TEMPLATE_VERSION
    assert pet_only.template_version == PET_ONLY_VIDEO_BIBLE_TEMPLATE_VERSION
    assert pet_only.template_version == "video-bible-pet-only-v1.0.5"
    assert pet_only.result_model is PetOnlyVideoBibleDraft
    assert pet_only.max_output_tokens == base.max_output_tokens
    assert pet_only.max_model_attempts == base.max_model_attempts

    # Strict slug instruction : failure still rejects rather than silently rewriting IDs.
    assert "subject.subject_id" in PET_ONLY_STORY_DIRECTOR_INSTRUCTIONS
    assert "^[A-Za-z0-9_.-]+$" in pet_only.system_prompt
    assert "pet:maotai is NOT a valid subject_id" in pet_only.system_prompt
