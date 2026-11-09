from __future__ import annotations

import pytest
from pydantic import ValidationError

from picotoopet_core.creative.models import CreativeScriptResult
from picotoopet_core.creative.state_spine import (
    UnlockedVideoBibleProposalV1,
    bind_pet_only_video_bible,
    bound_bible_integrity_findings,
    build_state_spine,
    canonical_json,
    seal_state_facts,
    verify_compiled_shot_locks,
    verify_shot_plan_prompt_locks,
)
from picotoopet_core.creative.video_bible import (
    derive_shot_plan,
    expanded_shot_fields,
    seal_bible,
)
from tests.creative_quality_2026 import story_fixture_2026 as story_fx
from tests.unit.creative.test_state_facts_v1 import state_facts_payload


def _proposal() -> dict:
    return {
        "schema_version": "state_spine_proposal.v1",
        "shots": [
            {
                "shot_id": "shot-001",
                "beat_id": "beat-001",
                "event": "BLINK_AND_REOPEN",
                "creative_emphasis": "CALM_OBSERVATIONAL",
                "camera_framing": "locked medium shot",
            },
            {
                "shot_id": "shot-002",
                "beat_id": "beat-002",
                "event": "SUBTLE_BREATHING",
                "creative_emphasis": "DETAIL",
                "camera_framing": "locked medium close-up",
            },
            {
                "shot_id": "shot-003",
                "beat_id": "beat-003",
                "event": "SUBTLE_BREATHING",
                "creative_emphasis": "CALM_OBSERVATIONAL",
                "camera_framing": "locked medium shot",
            },
        ],
        "needs_deep_ai": False,
        "needs_human": False,
    }


def _script() -> CreativeScriptResult:
    return CreativeScriptResult.model_validate(story_fx.script())


def test_state_spine_is_byte_deterministic_and_handoffs_share_state_ids() -> None:
    facts = seal_state_facts(state_facts_payload())
    events = ["BLINK_AND_REOPEN", "SUBTLE_BREATHING", "SUBTLE_BREATHING"]
    first = build_state_spine(facts, events)
    second = build_state_spine(facts, events)

    assert canonical_json(first.model_dump(mode="json")) == canonical_json(
        second.model_dump(mode="json")
    )
    assert first.spine_digest == second.spine_digest
    assert [state.state_id for state in first.states] == ["S0", "S1", "S2", "S3"]
    assert [(item.opening_state_id, item.closing_state_id) for item in first.transitions] == [
        ("S0", "S1"),
        ("S1", "S2"),
        ("S2", "S3"),
    ]
    assert first.states[1].eye_state == "OPEN"
    assert first.states[1].pose_lock_id == facts.pose_lock.pose_lock_id


def test_state_spine_rejects_an_event_not_authorized_by_owner_facts() -> None:
    facts = seal_state_facts(state_facts_payload())

    with pytest.raises(ValueError, match="STATE_SPINE_EVENT_NOT_AUTHORIZED"):
        build_state_spine(facts, ["BLINK_AND_REOPEN", "HEAD_TURN", "SUBTLE_BREATHING"])


@pytest.mark.parametrize("field", ["subject", "pose_lock"])
def test_model_contract_cannot_contain_or_rewrite_locked_fields(field: str) -> None:
    proposal = _proposal()
    proposal[field] = {"species": "dog"} if field == "subject" else {"body_pose": "standing"}

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        UnlockedVideoBibleProposalV1.model_validate(proposal)


def test_binder_rejects_event_or_framing_conflicts_instead_of_overwriting() -> None:
    facts = seal_state_facts(state_facts_payload())
    spine = build_state_spine(
        facts, ["BLINK_AND_REOPEN", "SUBTLE_BREATHING", "SUBTLE_BREATHING"]
    )
    proposal = _proposal()
    proposal["shots"][1]["event"] = "BLINK_AND_REOPEN"

    with pytest.raises(ValueError, match="STATE_SPINE_EVENT_CONFLICT:shot-002"):
        bind_pet_only_video_bible(
            facts,
            spine,
            UnlockedVideoBibleProposalV1.model_validate(proposal),
            _script(),
            require_story_payoff=False,
        )

    proposal = _proposal()
    proposal["shots"][2]["camera_framing"] = "wide orbit shot"
    with pytest.raises(ValueError, match="STATE_SPINE_CAMERA_FRAMING_CONFLICT:shot-003"):
        bind_pet_only_video_bible(
            facts,
            spine,
            UnlockedVideoBibleProposalV1.model_validate(proposal),
            _script(),
            require_story_payoff=False,
        )


def test_binder_builds_existing_bible_contract_and_every_shot_contains_all_locks() -> None:
    facts = seal_state_facts(state_facts_payload())
    spine = build_state_spine(
        facts, ["BLINK_AND_REOPEN", "SUBTLE_BREATHING", "SUBTLE_BREATHING"]
    )
    draft = bind_pet_only_video_bible(
        facts,
        spine,
        UnlockedVideoBibleProposalV1.model_validate(_proposal()),
        _script(),
        require_story_payoff=False,
    )

    assert draft.schema_version == "video_bible.v1"
    assert draft.product is None
    assert [shot.opening_state for shot in draft.shots] == [
        "state_ref=S0;pose_lock_id=pose-seated-forward",
        "state_ref=S1;pose_lock_id=pose-seated-forward",
        "state_ref=S2;pose_lock_id=pose-seated-forward",
    ]
    assert [shot.closing_state for shot in draft.shots] == [
        "state_ref=S1;pose_lock_id=pose-seated-forward",
        "state_ref=S2;pose_lock_id=pose-seated-forward",
        "state_ref=S3;pose_lock_id=pose-seated-forward",
    ]
    assert all(verify_compiled_shot_locks(draft, shot, facts) == () for shot in draft.shots)
    for shot in draft.shots:
        compiled = expanded_shot_fields(draft, shot)
        flat = canonical_json(compiled).decode("utf-8")
        assert facts.subject_lock.coat_or_appearance in flat
        assert facts.pose_lock.body_pose in flat
        assert facts.scene_lock.environment in flat
        assert "locked-off tripod camera, no camera movement" in flat


def test_current_blink_and_breathing_only_story_gate_conflict_stops_binding() -> None:
    facts = seal_state_facts(state_facts_payload())
    spine = build_state_spine(
        facts, ["BLINK_AND_REOPEN", "SUBTLE_BREATHING", "SUBTLE_BREATHING"]
    )

    assert spine.story_change_authorized is False
    assert spine.reason_codes == ("STATE_SPINE_STORY_NO_CHANGE_CONFLICT",)
    with pytest.raises(ValueError, match="STATE_SPINE_STORY_NO_CHANGE_CONFLICT"):
        bind_pet_only_video_bible(
            facts,
            spine,
            UnlockedVideoBibleProposalV1.model_validate(_proposal()),
            _script(),
            require_story_payoff=True,
        )


_EVENTS = ["BLINK_AND_REOPEN", "SUBTLE_BREATHING", "SUBTLE_BREATHING"]


def test_generic_spine_never_self_declares_a_story_payoff_for_static_events() -> None:
    """#236 contract: the spine flag stays False; opt-in acceptance is a separate verifier."""

    facts = seal_state_facts(state_facts_payload())
    spine = build_state_spine(facts, _EVENTS)

    assert spine.story_change_authorized is False
    assert spine.reason_codes == ("STATE_SPINE_STORY_NO_CHANGE_CONFLICT",)


def test_bound_bible_integrity_rejects_wrong_action_and_handoff() -> None:
    facts = seal_state_facts(state_facts_payload())
    spine = build_state_spine(facts, _EVENTS)
    draft = bind_pet_only_video_bible(
        facts,
        spine,
        UnlockedVideoBibleProposalV1.model_validate(_proposal()),
        _script(),
        require_story_payoff=False,
    )
    assert bound_bible_integrity_findings(draft, facts, spine) == ()

    corrupted = draft.model_copy(
        update={
            "shots": [
                draft.shots[0].model_copy(update={"visible_action": "the subject turns its head"}),
                *draft.shots[1:],
            ]
        }
    )
    assert bound_bible_integrity_findings(corrupted, facts, spine) == (
        "BOUND_BIBLE_ACTION_MISMATCH:shot-001",
    )


def test_derived_prompt_projection_rejects_any_missing_lock() -> None:
    facts = seal_state_facts(state_facts_payload())
    spine = build_state_spine(facts, _EVENTS)
    draft = bind_pet_only_video_bible(
        facts,
        spine,
        UnlockedVideoBibleProposalV1.model_validate(_proposal()),
        _script(),
        require_story_payoff=False,
    )
    bible = seal_bible(
        draft,
        project_key="goal-synthetic",
        source_set_digest="d" * 64,
        selected_idea_id="idea-001",
    )
    plan = derive_shot_plan(bible, _script())
    assert verify_shot_plan_prompt_locks(plan, facts) == ()

    plan["shots"][1]["subject"] = "generic pet"
    assert "PROMPT_LOCK_MISSING:shot-002:SUBJECT_ID" in verify_shot_plan_prompt_locks(
        plan, facts
    )
