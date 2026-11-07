"""Strictly opt-in static pet story *plan* acceptance, not visual acceptance.

This pure verifier has no database, owner credential, scheduler or production route.
An actual owner policy approval must be resolved from Core's canonical ledger by a
trusted caller; passing a client-supplied document is never enough for production.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import CreativeScriptResult
from .state_spine import (
    AllowedEvent,
    BreathingState,
    EyeState,
    StateFactsV1,
    StateSpineV1,
    UnlockedVideoBibleProposalV1,
    build_state_spine,
    canonical_sha256,
)

_DIGEST = r"^[0-9a-f]{64}$"
_EXPECTED_EVENTS = (
    AllowedEvent.BLINK_AND_REOPEN,
    AllowedEvent.SUBTLE_BREATHING,
    AllowedEvent.SUBTLE_BREATHING,
)


class StaticPetStoryOptInV1(BaseModel):
    """Immutable reference to an independently verified, owner-approved policy decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["static_pet_story_opt_in.v1"] = "static_pet_story_opt_in.v1"
    policy_id: Literal["static-pet-story-v1.0.0"] = "static-pet-story-v1.0.0"
    goal_id: str = Field(min_length=1, max_length=128)
    review_actor_id: str = Field(min_length=1, max_length=80)
    commitment_id: str = Field(min_length=1, max_length=160)
    review_digest: str = Field(pattern=_DIGEST)
    subject_key: str = Field(pattern=r"^pet:[a-z0-9][a-z0-9-]{1,63}$")
    source_set_digest: str = Field(pattern=_DIGEST)
    objective_digest: str = Field(pattern=_DIGEST)
    facts_digest: str = Field(pattern=_DIGEST)


@dataclass(frozen=True, slots=True)
class StaticPetStoryDecision:
    """Explicit semantic result; never proof of a rendered or accepted frame."""

    outcome: Literal["ACCEPT", "NEEDS_HUMAN"]
    reason_codes: tuple[str, ...]
    static_temporal_payoff_accepted: bool
    model_calls: Literal[0] = 0


def evaluate_static_pet_story(
    *,
    facts: StateFactsV1,
    spine: StateSpineV1,
    proposal: UnlockedVideoBibleProposalV1,
    script: CreativeScriptResult,
    opt_in: StaticPetStoryOptInV1 | None,
    verify_owner_commitment: Callable[[StaticPetStoryOptInV1], bool] | None,
) -> StaticPetStoryDecision:
    """Pure typed acceptance; a verified Core owner decision is mandatory.

    A trusted future Core integrator must check the actual commitment ID, actor,
    policy selection, Goal, subject and source digests inside the authenticated
    canonical ledger. This function deliberately does not fetch or forge evidence.
    """

    reasons: list[str] = []
    if opt_in is None:
        reasons.append("STATIC_STORY_EXPLICIT_OPT_IN_MISSING")
    elif verify_owner_commitment is None:
        reasons.append("STATIC_STORY_OWNER_REVIEW_UNVERIFIED")
    else:
        # The supplied callback is the ONLY authority to confirm actual Core ledger
        # ownership; untrusted API clients must never select this callback.
        if not verify_owner_commitment(opt_in):
            reasons.append("STATIC_STORY_OWNER_REVIEW_UNVERIFIED")

    if opt_in is not None and (
        opt_in.subject_key != facts.subject_key
        or not hmac.compare_digest(opt_in.source_set_digest, facts.source_set_digest)
        or not hmac.compare_digest(opt_in.objective_digest, facts.objective_digest)
        or not hmac.compare_digest(opt_in.facts_digest, facts.facts_digest)
    ):
        reasons.append("STATIC_STORY_SCOPE_DIGEST_MISMATCH")

    if not facts.pet_only or not facts.new_job_only or facts.creative_profile != (
        "creative.content_plan.v2"
    ):
        reasons.append("STATIC_STORY_LEGACY_PROFILE_FORBIDDEN")

    if not facts.pose_lock.fixed or facts.camera_lock.movement != "STATIC":
        reasons.append("STATIC_STORY_LOCK_INVALID")

    if spine.facts_digest != facts.facts_digest:
        reasons.append("STATIC_STORY_SPINE_FACTS_MISMATCH")

    # Recompute every typed transition and state: S0 != S3 is NOT a story payoff.
    try:
        expected = build_state_spine(facts, list(_EXPECTED_EVENTS))
    except ValueError:
        reasons.append("STATIC_STORY_EVENTS_NOT_SOURCE_AUTHORIZED")
    else:
        if (
            spine.spine_digest != canonical_sha256(
                spine.model_dump(mode="json"), "spine_digest"
            )
            or spine.states != expected.states
            or spine.transitions != expected.transitions
            or spine.story_change_authorized
        ):
            reasons.append("STATIC_STORY_STATE_SPINE_DRIFT")

        if any(
            item.eye_state is not EyeState.OPEN
            or item.pose_lock_id != facts.pose_lock.pose_lock_id
            or item.scene_lock_id != facts.scene_lock.scene_lock_id
            or item.subject_lock_id != facts.subject_lock.subject_id
            or item.camera_lock_id != facts.camera_lock.camera_lock_id
            for item in spine.states
        ):
            reasons.append("STATIC_STORY_POSE_IDENTITY_OR_EYES_DRIFT")

        if (
            spine.states[0].breathing_state is not BreathingState.RESTING
            or spine.states[-1].breathing_state is not BreathingState.SUBTLE
        ):
            reasons.append("STATIC_STORY_BREATHING_STATE_INVALID")

    if proposal.needs_human or proposal.needs_deep_ai:
        reasons.append("STATIC_STORY_MODEL_DECLARED_REVIEW")

    if len(proposal.shots) != 3 or len(script.beats) != 3:
        reasons.append("STATIC_STORY_SHOT_COUNT_INVALID")
    else:
        framings: list[str] = []
        for index, (shot, beat) in enumerate(zip(proposal.shots, script.beats, strict=True)):
            expected_shot_id = f"shot-{index + 1:03d}"
            expected_event = _EXPECTED_EVENTS[index]
            if (
                shot.shot_id != expected_shot_id
                or shot.beat_id != beat.beat_id
                or shot.event is not expected_event
                or beat.order != index + 1
                or beat.duration_seconds != 4
            ):
                reasons.append(f"STATIC_STORY_SHOT_OR_EVENT_INVALID:{expected_shot_id}")
            if shot.camera_framing not in facts.camera_lock.allowed_framings:
                reasons.append(f"STATIC_STORY_FRAMING_NOT_AUTHORIZED:{expected_shot_id}")
            framings.append(shot.camera_framing)
        if any(first == second for first, second in zip(framings, framings[1:])):
            reasons.append("STATIC_STORY_FRAMING_NO_PROGRESSION")
        if script.target_duration_seconds != 12:
            reasons.append("STATIC_STORY_DURATION_INVALID")

    if reasons:
        return StaticPetStoryDecision("NEEDS_HUMAN", tuple(sorted(set(reasons))), False)
    return StaticPetStoryDecision(
        "ACCEPT", ("STATIC_STORY_TEMPORAL_PAYOFF_ACCEPTED",), True
    )
