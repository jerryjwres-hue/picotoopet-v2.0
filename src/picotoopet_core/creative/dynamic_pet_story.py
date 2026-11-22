"""Explicit P0 dynamic motion proposal, on the existing Video Bible contract.

Only the motion semantics are deterministic. User-authored spatial descriptions
are not physical measurements, verified reference images or Owner approval.
No task, package, production job or GPU authority is created here.
"""
from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import CreativeScriptResult
from .state_spine import canonical_sha256
from .video_bible import (
    ArcBeat,
    BeatRole,
    CameraMovement,
    CameraRules,
    Featured,
    Handoff,
    NegativeConcept,
    PetOnlyVideoBibleDraft,
    SceneSpec,
    ShotBible,
    SubjectIdentity,
)

if TYPE_CHECKING:
    from picotoopet_core.domain.storypack import StoryPackV1

DYNAMIC_PET_POLICY = "dynamic-pet-feeding-v1.0.0"
_BoundedPhrase = Annotated[str, Field(min_length=1, max_length=80)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class MotionEvent(StrEnum):
    NOTICE_BOWL = "NOTICE_BOWL"
    APPROACH_BOWL = "APPROACH_BOWL"
    BEGIN_EATING = "BEGIN_EATING"


class MotionFraming(StrEnum):
    WIDE = "wide full-body shot"
    MEDIUM = "medium full-body shot"
    CLOSE = "close shot of muzzle and bowl"


class MotionShot(_Strict):
    shot_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$", max_length=80)
    event: MotionEvent
    framing: MotionFraming


class DynamicFeedingV1(_Strict):
    """Explicit authored motion choices, separate from the legacy static policy."""

    policy: Literal["dynamic-pet-feeding-v1.0.0"] = DYNAMIC_PET_POLICY
    start_location: _BoundedPhrase
    bowl_location: _BoundedPhrase
    support_surface: _BoundedPhrase
    bowl_description: _BoundedPhrase
    screen_direction: Literal["LEFT_TO_RIGHT", "RIGHT_TO_LEFT"]
    shots: tuple[MotionShot, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def check_motion(self) -> DynamicFeedingV1:
        if [s.event for s in self.shots] != list(MotionEvent):
            raise ValueError("DYNAMIC_EVENT_ORDER_INVALID")
        if len({s.shot_id.casefold() for s in self.shots}) != 3:
            raise ValueError("DYNAMIC_SHOT_ID_DUPLICATE")
        if len({s.framing for s in self.shots}) != 3:
            raise ValueError("DYNAMIC_FRAMING_PROGRESSION_REQUIRED")
        if self.shots[1].framing is MotionFraming.CLOSE:
            raise ValueError("DYNAMIC_APPROACH_REQUIRES_BODY_IN_FRAME")
        if self.start_location.casefold() == self.bowl_location.casefold():
            raise ValueError("DYNAMIC_APPROACH_REQUIRES_DISTINCT_LOCATIONS")
        if any("\n" in v or "\r" in v for v in (
            self.start_location, self.bowl_location,
            self.support_surface, self.bowl_description,
        )):
            raise ValueError("DYNAMIC_SPATIAL_PHRASE_INVALID")
        return self


class MotionState(_Strict):
    state_id: Literal["S0", "S1", "S2", "S3"]
    location: Literal["START", "AT_BOWL"]
    posture: Literal["STANDING", "STANDING_HEAD_LOWERED"]
    gaze: Literal["NOT_ON_BOWL", "ON_BOWL"]
    feeding: Literal["NOT_EATING", "EATING"]


# 01. Core owns these state mutations; no model may independently rewrite handoffs.
def _states() -> tuple[MotionState, ...]:
    return (
        MotionState(state_id="S0", location="START", posture="STANDING",
                    gaze="NOT_ON_BOWL", feeding="NOT_EATING"),
        MotionState(state_id="S1", location="START", posture="STANDING",
                    gaze="ON_BOWL", feeding="NOT_EATING"),
        MotionState(state_id="S2", location="AT_BOWL", posture="STANDING",
                    gaze="ON_BOWL", feeding="NOT_EATING"),
        MotionState(state_id="S3", location="AT_BOWL", posture="STANDING_HEAD_LOWERED",
                    gaze="ON_BOWL", feeding="EATING"),
    )


def _state_text(state: MotionState, motion: DynamicFeedingV1) -> str:
    location = motion.start_location if state.location == "START" else motion.bowl_location
    posture = "standing, head lowered" if state.posture == "STANDING_HEAD_LOWERED" else "standing"
    gaze = "looking at the bowl" if state.gaze == "ON_BOWL" else "looking away from the bowl"
    feeding = "eating" if state.feeding == "EATING" else "not eating"
    return f"{posture} at {location}, {gaze}, {feeding}"


def _action_text(event: MotionEvent, motion: DynamicFeedingV1) -> str:
    # 02. One dominant action per shot; don't ask the renderer to teleport or
    #     combine walking, sitting, and eating into a single four-second task.
    if event is MotionEvent.NOTICE_BOWL:
        return "the pet turns its gaze toward the bowl while staying in place"
    if event is MotionEvent.APPROACH_BOWL:
        direction = "left to right" if motion.screen_direction == "LEFT_TO_RIGHT" else "right to left"
        return f"the pet walks {direction} toward the stationary bowl across the support surface"
    return "the pet takes its first bites from the stationary bowl"


def build_dynamic_motion_proposal(pack: StoryPackV1) -> dict:
    """Return a deterministic review candidate; preserve authored text alongside it."""
    motion = pack.dynamic_motion
    if motion is None:
        raise ValueError("DYNAMIC_MOTION_NOT_SELECTED")
    if (
        pack.output_profile != "p0_landscape"
        or len(pack.shots) != 3
        or pack.supporting_character_refs
        or pack.additional_scene_refs
        or pack.style_ref is None
        or [item.shot_id for item in motion.shots] != [item.id for item in pack.shots]
        or any(
            item.cast_refs not in (None, [pack.character_ref])
            or item.scene_ref not in (None, pack.scene_ref)
            or (index > 0 and item.handoff != "continuous")
            for index, item in enumerate(pack.shots)
        )
    ):
        raise ValueError("DYNAMIC_STORY_P0_SCOPE_INVALID")

    states = _states()
    shots = []
    for index, (source, choice) in enumerate(zip(pack.shots, motion.shots, strict=True)):
        shots.append({
            "shot_id": source.id,
            "event": choice.event.value,
            "framing": choice.framing.value,
            "opening_state": _state_text(states[index], motion),
            "visible_action": _action_text(choice.event, motion),
            "closing_state": _state_text(states[index + 1], motion),
            "source_action": source.action,
            "source_state_in": source.state_in,
            "source_state_out": source.state_out,
            "source_because": source.because,
            "duration_seconds": 4,
        })
    document = {
        "policy": motion.policy,
        "storypack_sha256": canonical_sha256(pack.model_dump(mode="json")),
        "motion": motion.model_dump(mode="json"),
        "states": [state.model_dump(mode="json") for state in states],
        "shots": shots,
    }
    # 03. A changing typed state is only a *planned* payoff; no visual claim.
    return {
        **document,
        "motion_digest": canonical_sha256(document),
        "status": "DYNAMIC_PROPOSAL_REQUIRES_OWNER_REVIEW",
        "planned_payoff": "START_NOT_EATING_TO_AT_BOWL_EATING",
        "owner_approved": False,
        "can_queue": False,
        "gpu_post_authorized": False,
    }


def bind_dynamic_bible_proposal(
    pack: StoryPackV1,
    script: CreativeScriptResult,
    subject: SubjectIdentity,
    scene: SceneSpec,
) -> PetOnlyVideoBibleDraft:
    """Project to the existing Bible draft; deliberately impossible to auto-pass.

    Identity/scene text must eventually be resolved from canonical structured
    Owner evidence. This pure draft adapter is not an owner review or executor.
    """
    review = build_dynamic_motion_proposal(pack)
    motion = pack.dynamic_motion
    if motion is None:
        raise ValueError("DYNAMIC_MOTION_NOT_SELECTED")
    if (
        subject.kind != "PET"
        or len(script.beats) != 3
        or script.target_duration_seconds != 12
        or any(beat.duration_seconds != 4 for beat in script.beats)
        or script.cta_beat_id != script.beats[-1].beat_id
    ):
        raise ValueError("DYNAMIC_SCRIPT_SCOPE_INVALID")

    # 04. Reuse the one existing Bible -> ShotPlan projection, not a render engine.
    shots = [
        ShotBible(
            shot_id=item["shot_id"], beat_id=beat.beat_id, order=index + 1,
            scene_id=scene.scene_id, duration_seconds=4,
            featured=[Featured.SUBJECT],
            opening_state=item["opening_state"], visible_action=item["visible_action"],
            closing_state=item["closing_state"], camera_framing=item["framing"],
            camera_movement=CameraMovement.STATIC,
            handoff_to_next=Handoff.CONTINUOUS,
        )
        for index, (item, beat) in enumerate(zip(review["shots"], script.beats, strict=True))
    ]
    return PetOnlyVideoBibleDraft(
        subject=subject,
        scenes=[scene],
        camera_rules=CameraRules(
            screen_direction=motion.screen_direction,
            allowed_movements=[CameraMovement.STATIC],
        ),
        continuity_anchors=[
            f"fixed bowl appearance: {motion.bowl_description}",
            f"fixed bowl position: {motion.bowl_location}",
            f"fixed support surface: {motion.support_surface}",
            "same pet identity, lighting and scene throughout",
        ],
        global_continuity_notes=[f"dynamic_motion_digest={review['motion_digest']}"],
        arc=[ArcBeat(beat_id=beat.beat_id, role=role) for beat, role in zip(
            script.beats, [BeatRole.HOOK, BeatRole.DEMO, BeatRole.CTA], strict=True
        )],
        shots=shots,
        negative_concepts=[
            NegativeConcept.EXTRA_LIMBS, NegativeConcept.MORPHING,
            NegativeConcept.DUPLICATED_OBJECTS,
        ],
        unverified_fields=["dynamic_owner_review", "reference_master_approval"],
        needs_human=True,
    )
