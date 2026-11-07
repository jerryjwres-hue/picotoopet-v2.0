from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from picotoopet_core.creative.director import PET_ONLY_VIDEO_BIBLE_TEMPLATE_VERSION
from picotoopet_core.creative.models import CreativeBriefResult, CreativeScriptResult
from picotoopet_core.creative.profiles import (
    creative_profile_definition,
    pet_only_video_bible_stage,
)
from picotoopet_core.creative.state_spine import (
    STATE_SPINE_TEMPLATE_VERSION,
    UnlockedVideoBibleProposalV1,
    bind_pet_only_video_bible,
    build_state_spine,
    canonical_sha256,
    seal_state_facts,
)
from picotoopet_core.creative.video_bible import (
    derive_shot_plan,
    evaluate_video_bible,
    seal_bible,
)
from tests.creative_quality_2026 import story_fixture_2026 as story_fx
from tests.unit.creative.test_state_facts_v1 import state_facts_payload
from tests.unit.creative.test_state_spine_v110 import _proposal

FIXTURE = (
    Path(__file__).parents[2] / "fixtures/creative/pr228_state_spine_regression.json"
)


def _bound_draft():
    facts = seal_state_facts(state_facts_payload())
    spine = build_state_spine(
        facts, ["BLINK_AND_REOPEN", "SUBTLE_BREATHING", "SUBTLE_BREATHING"]
    )
    draft = bind_pet_only_video_bible(
        facts,
        spine,
        UnlockedVideoBibleProposalV1.model_validate(_proposal()),
        CreativeScriptResult.model_validate(story_fx.script()),
        require_story_payoff=False,
    )
    return facts, spine, draft


def test_retained_pr228_regression_record_is_frozen_and_not_real_subject_evidence() -> None:
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert record["baseline_id"] == "pr228-v105-new-synthetic-mochi-fixed-pose-v1"
    assert record["combined_baseline_sha256"] == (
        "ea9ef7ab7c85857e79660c041846531e9115681facf9b9d3bd50dcae015272fc"
    )
    assert record["fixture_digest"] == canonical_sha256(record, "fixture_digest")
    assert record["source_taxonomy"] != record["attempt_2_taxonomy"]
    assert record["source_pose"]["head_direction_present"] is False
    assert record["source_camera"]["explicit_allowed_framings_present"] is False
    assert "not the real Maotai objective" in record["fixture_scope_note"]


def test_frozen_model_taxonomy_cannot_replace_the_bound_source_taxonomy() -> None:
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload = state_facts_payload()
    payload["subject_lock"]["species"] = record["source_taxonomy"]["species"]
    binding = next(
        item
        for item in payload["subject_lock"]["evidence_bindings"]
        if item["field_path"] == "subject_lock.species"
    )
    binding["value_digest"] = canonical_sha256(record["source_taxonomy"]["species"])
    sealed = seal_state_facts(payload).model_dump(mode="json")

    drifted = deepcopy(sealed)
    drifted["subject_lock"]["species"] = record["attempt_2_taxonomy"]["species"]
    with pytest.raises(ValidationError, match="STATE_FACT_BINDING_VALUE_MISMATCH"):
        type(seal_state_facts(payload)).model_validate(drifted)


def test_existing_video_bible_quality_review_still_evaluates_bound_draft() -> None:
    _, _, draft = _bound_draft()
    findings = evaluate_video_bible(
        draft,
        brief=CreativeBriefResult.model_validate(story_fx.brief()),
        script=CreativeScriptResult.model_validate(story_fx.script()),
        evidence_ids={story_fx.EVIDENCE},
        required_shot_count=3,
        required_shot_seconds=4.0,
        story_gate=False,
        pet_only=True,
    )

    assert findings == []


def test_existing_seal_and_shot_plan_compiler_keep_all_lock_text() -> None:
    facts, _, draft = _bound_draft()
    bible = seal_bible(
        draft,
        project_key="synthetic-state-spine-v110",
        source_set_digest=facts.source_set_digest,
        selected_idea_id="idea-001",
    )
    plan = derive_shot_plan(bible, CreativeScriptResult.model_validate(story_fx.script()))
    serialized = json.dumps(plan, ensure_ascii=False, sort_keys=True)

    for phrase in (
        facts.subject_lock.coat_or_appearance,
        facts.pose_lock.body_pose,
        facts.pose_lock.head_direction,
        facts.pose_lock.support_surface,
        facts.scene_lock.environment,
        facts.scene_lock.lighting,
        *facts.subject_lock.distinguishing_marks,
    ):
        assert phrase in serialized


def test_new_contract_is_not_activated_for_legacy_or_existing_pet_only_jobs() -> None:
    legacy = creative_profile_definition("creative.content_plan.v1")
    v2 = creative_profile_definition("creative.content_plan.v2")
    existing_pet_only = pet_only_video_bible_stage(v2.stages[3])

    assert [stage.template_version for stage in legacy.stages] == [
        "idea-ranking-v1.0.0",
        "creative-brief-v1.0.0",
        "creative-script-v1.0.0",
        "shot-plan-v1.0.0",
    ]
    assert PET_ONLY_VIDEO_BIBLE_TEMPLATE_VERSION == "video-bible-pet-only-v1.0.4"
    assert existing_pet_only.template_version == PET_ONLY_VIDEO_BIBLE_TEMPLATE_VERSION
    assert STATE_SPINE_TEMPLATE_VERSION == "video-bible-pet-only-v1.1.0"
