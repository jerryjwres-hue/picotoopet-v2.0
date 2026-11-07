"""P0 #233: only real temporal beats count, never differences in state IDs."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from picotoopet_core.creative.models import CreativeScriptResult
from picotoopet_core.creative.state_spine import (
    UnlockedVideoBibleProposalV1,
    build_state_spine,
    canonical_sha256,
    seal_state_facts,
)
from picotoopet_core.creative.static_pet_story import (
    StaticPetStoryDecision,
    StaticPetStoryOptInV1,
    evaluate_static_pet_story,
)
from tests.creative_quality_2026 import story_fixture_2026 as story_fx
from tests.unit.creative.test_state_facts_v1 import state_facts_payload
from tests.unit.creative.test_state_spine_v110 import _proposal


def _case():
    facts = seal_state_facts(state_facts_payload())
    spine = build_state_spine(
        facts, ["BLINK_AND_REOPEN", "SUBTLE_BREATHING", "SUBTLE_BREATHING"]
    )
    proposal = UnlockedVideoBibleProposalV1.model_validate(_proposal())
    script = CreativeScriptResult.model_validate(story_fx.script())
    opt_in = StaticPetStoryOptInV1(
        goal_id="goal-new-synthetic-static",
        review_actor_id="synthetic-owner-actor",
        commitment_id="evidence-synthetic-static-policy-approved",
        review_digest="c" * 64,
        subject_key=facts.subject_key,
        source_set_digest=facts.source_set_digest,
        objective_digest=facts.objective_digest,
        facts_digest=facts.facts_digest,
    )
    return facts, spine, proposal, script, opt_in


def _evaluate(*, facts=None, spine=None, proposal=None, script=None, opt_in=None, verify=None):
    original = _case()
    return evaluate_static_pet_story(
        facts=facts or original[0],
        spine=spine or original[1],
        proposal=proposal or original[2],
        script=script or original[3],
        opt_in=opt_in if opt_in is not None else original[4],
        verify_owner_commitment=verify,
    )


def test_owner_verified_blink_breathing_framing_is_valid_static_temporal_payoff() -> None:
    facts, spine, proposal, script, opt_in = _case()

    # Reversible blink        : opening and terminal eye states can remain identical.
    assert spine.states[0].eye_state == spine.states[-1].eye_state == "OPEN"
    assert spine.states[0].pose_lock_id == spine.states[-1].pose_lock_id
    assert spine.story_change_authorized is False

    result = evaluate_static_pet_story(
        facts=facts,
        spine=spine,
        proposal=proposal,
        script=script,
        opt_in=opt_in,
        verify_owner_commitment=lambda record: record.commitment_id == opt_in.commitment_id,
    )
    assert result == StaticPetStoryDecision(
        "ACCEPT", ("STATIC_STORY_TEMPORAL_PAYOFF_ACCEPTED",), True
    )
    assert result.model_calls == 0


def test_no_opt_in_or_unverified_owner_cannot_enable_static_policy() -> None:
    facts, spine, proposal, script, opt_in = _case()
    for item, checker, expected in (
        (None, None, "STATIC_STORY_EXPLICIT_OPT_IN_MISSING"),
        (opt_in, None, "STATIC_STORY_OWNER_REVIEW_UNVERIFIED"),
        (opt_in, lambda record: False, "STATIC_STORY_OWNER_REVIEW_UNVERIFIED"),
    ):
        result = evaluate_static_pet_story(
            facts=facts,
            spine=spine,
            proposal=proposal,
            script=script,
            opt_in=item,
            verify_owner_commitment=checker,
        )
        assert result.outcome == "NEEDS_HUMAN"
        assert expected in result.reason_codes
        assert result.static_temporal_payoff_accepted is False


def test_scope_and_source_digest_mismatch_never_passes() -> None:
    facts, spine, proposal, script, opt_in = _case()
    for modified in (
        opt_in.model_copy(update={"subject_key": "pet:other"}),
        opt_in.model_copy(update={"source_set_digest": "f" * 64}),
        opt_in.model_copy(update={"objective_digest": "f" * 64}),
        opt_in.model_copy(update={"facts_digest": "f" * 64}),
    ):
        result = evaluate_static_pet_story(
            facts=facts, spine=spine, proposal=proposal, script=script,
            opt_in=modified, verify_owner_commitment=lambda record: True,
        )
        assert "STATIC_STORY_SCOPE_DIGEST_MISMATCH" in result.reason_codes
        assert result.outcome == "NEEDS_HUMAN"

    with pytest.raises(ValidationError):
        StaticPetStoryOptInV1(**{**opt_in.model_dump(), "policy_id": "general-story"})


@pytest.mark.parametrize(
    ("index", "bad_event"),
    [
        (0, "SUBTLE_BREATHING"),
        (1, "BLINK_AND_REOPEN"),
        (2, "BLINK_AND_REOPEN"),
    ],
)
def test_wrong_typed_event_or_only_breathing_is_rejected(index: int, bad_event: str) -> None:
    facts, spine, proposal, script, opt_in = _case()
    payload = proposal.model_dump(mode="json")
    payload["shots"][index]["event"] = bad_event
    malformed = UnlockedVideoBibleProposalV1.model_validate(payload)
    result = evaluate_static_pet_story(
        facts=facts, spine=spine, proposal=malformed, script=script,
        opt_in=opt_in, verify_owner_commitment=lambda record: True,
    )
    assert result.outcome == "NEEDS_HUMAN"
    assert any(
        code.startswith("STATIC_STORY_SHOT_OR_EVENT_INVALID") for code in result.reason_codes
    )


def test_no_progress_in_framing_is_not_a_story_payoff() -> None:
    facts, spine, proposal, script, opt_in = _case()
    payload = proposal.model_dump(mode="json")
    for shot in payload["shots"]:
        shot["camera_framing"] = "locked medium shot"
    result = evaluate_static_pet_story(
        facts=facts, spine=spine,
        proposal=UnlockedVideoBibleProposalV1.model_validate(payload),
        script=script, opt_in=opt_in,
        verify_owner_commitment=lambda record: True,
    )
    assert "STATIC_STORY_FRAMING_NO_PROGRESSION" in result.reason_codes


def test_unknown_camera_or_model_locked_identity_cannot_pass() -> None:
    facts, spine, proposal, script, opt_in = _case()
    payload = proposal.model_dump(mode="json")
    payload["shots"][0]["camera_framing"] = "orbiting moving camera"
    result = evaluate_static_pet_story(
        facts=facts, spine=spine,
        proposal=UnlockedVideoBibleProposalV1.model_validate(payload),
        script=script, opt_in=opt_in,
        verify_owner_commitment=lambda record: True,
    )
    assert "STATIC_STORY_FRAMING_NOT_AUTHORIZED:shot-001" in result.reason_codes

    payload = proposal.model_dump(mode="json")
    payload["subject"] = {"species": "dog"}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        UnlockedVideoBibleProposalV1.model_validate(payload)


def test_state_ids_do_not_fake_visual_state_change() -> None:
    facts, spine, proposal, script, opt_in = _case()
    malformed_states = [state.model_copy(update={"eye_state": "HALF_CLOSED"})
                        for state in spine.states]
    corrupted = spine.model_copy(update={"states": tuple(malformed_states)})
    result = evaluate_static_pet_story(
        facts=facts, spine=corrupted, proposal=proposal, script=script,
        opt_in=opt_in, verify_owner_commitment=lambda record: True,
    )
    assert result.outcome == "NEEDS_HUMAN"
    assert "STATIC_STORY_STATE_SPINE_DRIFT" in result.reason_codes
    assert "STATIC_STORY_POSE_IDENTITY_OR_EYES_DRIFT" in result.reason_codes
    assert canonical_sha256(corrupted.model_dump(mode="json"), "spine_digest") != (
        corrupted.spine_digest
    )


def test_digest_valid_but_wrong_event_spine_does_not_get_policy_accept() -> None:
    facts, spine, proposal, script, opt_in = _case()
    changed = build_state_spine(
        facts, ["BLINK_AND_REOPEN", "SUBTLE_BREATHING", "BLINK_AND_REOPEN"]
    )
    assert changed.spine_digest != spine.spine_digest
    result = evaluate_static_pet_story(
        facts=facts, spine=changed, proposal=proposal, script=script,
        opt_in=opt_in, verify_owner_commitment=lambda record: True,
    )
    assert "STATIC_STORY_STATE_SPINE_DRIFT" in result.reason_codes


def test_no_legacy_profile_or_persistent_story_change_mutation() -> None:
    facts, spine, proposal, script, opt_in = _case()
    altered = spine.model_copy(update={"story_change_authorized": True})
    result = evaluate_static_pet_story(
        facts=facts, spine=altered, proposal=proposal, script=script,
        opt_in=opt_in, verify_owner_commitment=lambda record: True,
    )
    assert "STATIC_STORY_STATE_SPINE_DRIFT" in result.reason_codes
    invalid_facts = deepcopy(facts.model_dump(mode="json"))
    invalid_facts["creative_profile"] = "creative.content_plan.v1"
    with pytest.raises(ValidationError):
        seal_state_facts(invalid_facts)


def test_user_authorization_cannot_be_omitted_on_model_declared_review() -> None:
    facts, spine, proposal, script, opt_in = _case()
    changed = proposal.model_copy(update={"needs_human": True})
    result = evaluate_static_pet_story(
        facts=facts, spine=spine, proposal=changed, script=script,
        opt_in=opt_in, verify_owner_commitment=lambda record: True,
    )
    assert "STATIC_STORY_MODEL_DECLARED_REVIEW" in result.reason_codes
