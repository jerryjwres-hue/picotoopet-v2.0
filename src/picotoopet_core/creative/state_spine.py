"""Core-owned state locks for new pet-only v2 Creative jobs.

The module is deliberately pure.  It defines and validates a source-bound contract but does not
read owner evidence, persist facts, call a model, or activate a production stage.  Those actions
remain blocked until the authenticated owner review flow can capture the structured fields.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .models import CreativeScriptResult
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
    expanded_shot_fields,
)

STATE_FACTS_SCHEMA_VERSION = "state_facts.v1"
STATE_SPINE_TEMPLATE_VERSION = "video-bible-pet-only-v1.1.0"
STATIC_PET_STORY_POLICY = "static-pet-story-v1.0.0"
_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_ID_PATTERN = r"^[A-Za-z0-9_.-]+$"


def canonical_json(value: object, excluded_key: str | None = None) -> bytes:
    """Return the controller-approved compact, sorted UTF-8 representation."""

    body = value
    if excluded_key is not None and isinstance(value, dict):
        body = {key: item for key, item in value.items() if key != excluded_key}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def canonical_sha256(value: object, excluded_key: str | None = None) -> str:
    return hashlib.sha256(canonical_json(value, excluded_key)).hexdigest()


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthorityKind(StrEnum):
    OWNER_ATTESTATION = "OWNER_ATTESTATION"
    APPROVED_REFERENCE = "APPROVED_REFERENCE"
    OWNER_CREATIVE_INTENT = "OWNER_CREATIVE_INTENT"


class AllowedEvent(StrEnum):
    BLINK_AND_REOPEN = "BLINK_AND_REOPEN"
    SUBTLE_BREATHING = "SUBTLE_BREATHING"


class EvidenceBindingV1(_Strict):
    field_path: str = Field(min_length=3, max_length=160)
    evidence_id: str = Field(min_length=3, max_length=160)
    authority_kind: AuthorityKind
    owner_confirmed: Literal[True]
    review_digest: str = Field(pattern=_DIGEST_PATTERN)
    value_digest: str = Field(pattern=_DIGEST_PATTERN)


class _BoundLock(_Strict):
    evidence_bindings: list[EvidenceBindingV1] = Field(min_length=1, max_length=32)

    def _validate_bindings(self, prefix: str, values: dict[str, object]) -> None:
        expected = {f"{prefix}.{name}": value for name, value in values.items()}
        bindings = {item.field_path: item for item in self.evidence_bindings}
        if len(bindings) != len(self.evidence_bindings) or set(bindings) != set(expected):
            raise ValueError("STATE_FACT_BINDING_COVERAGE_INVALID")
        for path, value in expected.items():
            if bindings[path].value_digest != canonical_sha256(value):
                raise ValueError(f"STATE_FACT_BINDING_VALUE_MISMATCH:{path}")


class SubjectLockV1(_BoundLock):
    subject_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    species: str = Field(min_length=1, max_length=80)
    breed_or_type: str = Field(min_length=1, max_length=120)
    coat_or_appearance: str = Field(min_length=1, max_length=240)
    distinguishing_marks: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _bindings_match(self) -> SubjectLockV1:
        values = self.model_dump(mode="json", exclude={"evidence_bindings"})
        self._validate_bindings("subject_lock", values)
        taxonomy = {
            "subject_lock.subject_id",
            "subject_lock.species",
            "subject_lock.breed_or_type",
            "subject_lock.coat_or_appearance",
            "subject_lock.distinguishing_marks",
        }
        for binding in self.evidence_bindings:
            if (
                binding.field_path in taxonomy
                and binding.authority_kind is AuthorityKind.OWNER_CREATIVE_INTENT
            ):
                raise ValueError(
                    f"STATE_FACT_IDENTITY_AUTHORITY_INVALID:{binding.field_path}"
                )
        return self


class PoseLockV1(_BoundLock):
    pose_lock_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    body_pose: str = Field(min_length=1, max_length=240)
    head_direction: str = Field(min_length=1, max_length=160)
    support_surface: str = Field(min_length=1, max_length=200)
    fixed: Literal[True]

    @model_validator(mode="after")
    def _bindings_match(self) -> PoseLockV1:
        self._validate_bindings(
            "pose_lock", self.model_dump(mode="json", exclude={"evidence_bindings"})
        )
        return self


class SceneLockV1(_BoundLock):
    scene_lock_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    environment: str = Field(min_length=1, max_length=300)
    lighting: str = Field(min_length=1, max_length=200)
    temporary_accessories: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _bindings_match(self) -> SceneLockV1:
        self._validate_bindings(
            "scene_lock", self.model_dump(mode="json", exclude={"evidence_bindings"})
        )
        return self


class CameraLockV1(_BoundLock):
    camera_lock_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    movement: Literal["STATIC"]
    allowed_framings: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _bindings_match(self) -> CameraLockV1:
        self._validate_bindings(
            "camera_lock", self.model_dump(mode="json", exclude={"evidence_bindings"})
        )
        return self


class StateFactsV1(_Strict):
    schema_version: Literal["state_facts.v1"] = STATE_FACTS_SCHEMA_VERSION
    facts_id: str = Field(pattern=_ID_PATTERN, max_length=100)
    facts_version: int = Field(ge=1)
    creative_profile: Literal["creative.content_plan.v2"]
    pet_only: Literal[True]
    new_job_only: Literal[True]
    subject_key: str = Field(pattern=r"^pet:[a-z0-9][a-z0-9-]{1,63}$", max_length=68)
    source_set_digest: str = Field(pattern=_DIGEST_PATTERN)
    objective_digest: str = Field(pattern=_DIGEST_PATTERN)
    subject_lock: SubjectLockV1
    pose_lock: PoseLockV1
    scene_lock: SceneLockV1
    camera_lock: CameraLockV1
    allowed_events: list[AllowedEvent] = Field(min_length=1, max_length=8)
    facts_digest: str = Field(pattern=_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _digest_matches(self) -> StateFactsV1:
        document = self.model_dump(mode="json")
        if self.facts_digest != canonical_sha256(document, "facts_digest"):
            raise ValueError("STATE_FACTS_DIGEST_MISMATCH")
        if len(set(self.allowed_events)) != len(self.allowed_events):
            raise ValueError("STATE_FACTS_DUPLICATE_ALLOWED_EVENT")
        return self


def seal_state_facts(payload: dict[str, Any]) -> StateFactsV1:
    document = deepcopy({key: value for key, value in payload.items() if key != "facts_digest"})
    for lock_name in ("subject_lock", "pose_lock", "scene_lock", "camera_lock"):
        lock = document.get(lock_name)
        if isinstance(lock, dict) and isinstance(lock.get("evidence_bindings"), list):
            lock["evidence_bindings"] = sorted(
                lock["evidence_bindings"], key=lambda item: str(item.get("field_path", ""))
            )
    if isinstance(document.get("allowed_events"), list):
        document["allowed_events"] = sorted(document["allowed_events"])
    document["facts_digest"] = canonical_sha256(document)
    return StateFactsV1.model_validate(document)


@dataclass(frozen=True, slots=True)
class StateFactsReadiness:
    outcome: Literal["READY", "NEEDS_HUMAN"]
    reason_codes: tuple[str, ...]
    model_calls: Literal[0] = 0


def state_facts_readiness(payload: StateFactsV1 | dict[str, Any] | None) -> StateFactsReadiness:
    """A pure pre-model gate; invalid or absent owner facts always make zero calls."""

    if payload is None:
        return StateFactsReadiness("NEEDS_HUMAN", ("STATE_FACTS_MISSING",))
    try:
        if isinstance(payload, StateFactsV1):
            facts = payload
        else:
            facts = StateFactsV1.model_validate(payload)
    except (ValidationError, ValueError):
        return StateFactsReadiness("NEEDS_HUMAN", ("STATE_FACTS_INVALID",))
    return StateFactsReadiness("READY", ()) if facts else StateFactsReadiness(
        "NEEDS_HUMAN", ("STATE_FACTS_INVALID",)
    )


class EyeState(StrEnum):
    OPEN = "OPEN"


class BreathingState(StrEnum):
    RESTING = "RESTING"
    SUBTLE = "SUBTLE"


class SpineStateV1(_Strict):
    state_id: Literal["S0", "S1", "S2", "S3"]
    subject_lock_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    pose_lock_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    scene_lock_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    camera_lock_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    eye_state: EyeState
    breathing_state: BreathingState
    completed_events: tuple[AllowedEvent, ...] = Field(max_length=3)


class StateTransitionV1(_Strict):
    shot_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    opening_state_id: Literal["S0", "S1", "S2"]
    closing_state_id: Literal["S1", "S2", "S3"]
    event: AllowedEvent


class StateSpineV1(_Strict):
    schema_version: Literal["state_spine.v1"] = "state_spine.v1"
    facts_digest: str = Field(pattern=_DIGEST_PATTERN)
    states: tuple[SpineStateV1, ...] = Field(min_length=4, max_length=4)
    transitions: tuple[StateTransitionV1, ...] = Field(min_length=3, max_length=3)
    story_change_authorized: bool
    reason_codes: tuple[str, ...] = Field(max_length=8)
    spine_digest: str = Field(pattern=_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _integrity(self) -> StateSpineV1:
        if [item.state_id for item in self.states] != ["S0", "S1", "S2", "S3"]:
            raise ValueError("STATE_SPINE_STATE_ORDER_INVALID")
        handoffs = [
            (item.opening_state_id, item.closing_state_id) for item in self.transitions
        ]
        if handoffs != [("S0", "S1"), ("S1", "S2"), ("S2", "S3")]:
            raise ValueError("STATE_SPINE_HANDOFF_INVALID")
        if self.spine_digest != canonical_sha256(
            self.model_dump(mode="json"), "spine_digest"
        ):
            raise ValueError("STATE_SPINE_DIGEST_MISMATCH")
        return self


def build_state_spine(
    facts: StateFactsV1,
    events: list[AllowedEvent | str],
) -> StateSpineV1:
    """Build S0→S3 without asking a model to restate any locked state."""

    if len(events) != 3:
        raise ValueError("STATE_SPINE_REQUIRES_THREE_EVENTS")
    try:
        typed_events = tuple(AllowedEvent(item) for item in events)
    except ValueError as exc:
        raise ValueError("STATE_SPINE_EVENT_NOT_AUTHORIZED") from exc
    if any(item not in facts.allowed_events for item in typed_events):
        raise ValueError("STATE_SPINE_EVENT_NOT_AUTHORIZED")

    states: list[SpineStateV1] = []
    breathing = BreathingState.RESTING
    completed: list[AllowedEvent] = []
    for index in range(4):
        states.append(
            SpineStateV1(
                state_id=f"S{index}",
                subject_lock_id=facts.subject_lock.subject_id,
                pose_lock_id=facts.pose_lock.pose_lock_id,
                scene_lock_id=facts.scene_lock.scene_lock_id,
                camera_lock_id=facts.camera_lock.camera_lock_id,
                eye_state=EyeState.OPEN,
                breathing_state=breathing,
                completed_events=tuple(completed),
            )
        )
        if index < 3:
            event = typed_events[index]
            completed.append(event)
            if event is AllowedEvent.SUBTLE_BREATHING:
                breathing = BreathingState.SUBTLE

    transitions = tuple(
        StateTransitionV1(
            shot_id=f"shot-{index + 1:03d}",
            opening_state_id=f"S{index}",
            closing_state_id=f"S{index + 1}",
            event=event,
        )
        for index, event in enumerate(typed_events)
    )
    # Both approved events are reversible micro-motion.  The spine NEVER self-declares a story
    # payoff: a persistent-change flag cannot be faked.  Opted-in static stories are accepted only
    # by the separate pure verifier ``static_pet_story.evaluate_static_pet_story`` after Core
    # re-verifies the owner's committed policy selection in the canonical ledger.
    body: dict[str, Any] = {
        "schema_version": "state_spine.v1",
        "facts_digest": facts.facts_digest,
        "states": [item.model_dump(mode="json") for item in states],
        "transitions": [item.model_dump(mode="json") for item in transitions],
        "story_change_authorized": False,
        "reason_codes": ["STATE_SPINE_STORY_NO_CHANGE_CONFLICT"],
    }
    body["spine_digest"] = canonical_sha256(body)
    return StateSpineV1.model_validate(body)


class CreativeEmphasis(StrEnum):
    CALM_OBSERVATIONAL = "CALM_OBSERVATIONAL"
    DETAIL = "DETAIL"


class UnlockedShotProposalV1(_Strict):
    shot_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    beat_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    # The event is an echo of the Core-owned transition and must match exactly.
    event: AllowedEvent
    creative_emphasis: CreativeEmphasis
    camera_framing: str = Field(min_length=1, max_length=120)


class UnlockedVideoBibleProposalV1(_Strict):
    schema_version: Literal["state_spine_proposal.v1"] = "state_spine_proposal.v1"
    shots: tuple[UnlockedShotProposalV1, ...] = Field(min_length=3, max_length=3)
    needs_deep_ai: bool = False
    needs_human: bool = False


def _identity_phrase(facts: StateFactsV1) -> str:
    lock = facts.subject_lock
    marks = ", ".join(lock.distinguishing_marks) or "no additional distinguishing marks"
    return (
        f"{lock.subject_id}, {lock.breed_or_type} {lock.species}, "
        f"{lock.coat_or_appearance}, distinguishing marks: {marks}"
    )


def _continuity_anchors(facts: StateFactsV1) -> list[str]:
    pose = facts.pose_lock
    scene = facts.scene_lock
    camera = facts.camera_lock
    accessories = ", ".join(scene.temporary_accessories) or "none"
    framings = ", ".join(camera.allowed_framings)
    return [
        f"fixed body pose: {pose.body_pose}",
        f"fixed head direction: {pose.head_direction}",
        f"fixed support surface: {pose.support_surface}",
        f"fixed temporary accessories: {accessories}",
        f"fixed camera: locked-off tripod, no movement; allowed framings: {framings}",
    ]


def _visible_action(event: AllowedEvent, emphasis: CreativeEmphasis) -> str:
    suffix = (
        ", calm observational emphasis"
        if emphasis is CreativeEmphasis.CALM_OBSERVATIONAL
        else ", detail emphasis"
    )
    if event is AllowedEvent.BLINK_AND_REOPEN:
        action = "the subject holds the fixed pose, makes one brief blink, and reopens both eyes"
    else:
        action = "the subject holds the fixed pose with only subtle breathing visible"
    return action + suffix


def bind_pet_only_video_bible(
    facts: StateFactsV1,
    spine: StateSpineV1,
    proposal: UnlockedVideoBibleProposalV1,
    script: CreativeScriptResult,
    *,
    require_story_payoff: bool = True,
) -> PetOnlyVideoBibleDraft:
    """Bind unlocked choices into the existing Bible contract without silent correction."""

    if spine.facts_digest != facts.facts_digest:
        raise ValueError("STATE_SPINE_FACTS_DIGEST_MISMATCH")
    if require_story_payoff and not spine.story_change_authorized:
        raise ValueError("STATE_SPINE_STORY_NO_CHANGE_CONFLICT")
    if len(script.beats) != 3:
        raise ValueError("STATE_SPINE_SCRIPT_REQUIRES_THREE_BEATS")
    if proposal.needs_human or proposal.needs_deep_ai:
        raise ValueError("STATE_SPINE_MODEL_DECLARED_REVIEW")

    transitions = {item.shot_id: item for item in spine.transitions}
    script_ids = [item.beat_id for item in script.beats]
    if [item.beat_id for item in proposal.shots] != script_ids:
        raise ValueError("STATE_SPINE_BEAT_CONFLICT")
    if [item.shot_id for item in proposal.shots] != list(transitions):
        raise ValueError("STATE_SPINE_SHOT_ORDER_CONFLICT")

    shots: list[ShotBible] = []
    for index, item in enumerate(proposal.shots):
        transition = transitions[item.shot_id]
        if item.event is not transition.event:
            raise ValueError(f"STATE_SPINE_EVENT_CONFLICT:{item.shot_id}")
        if item.camera_framing not in facts.camera_lock.allowed_framings:
            raise ValueError(f"STATE_SPINE_CAMERA_FRAMING_CONFLICT:{item.shot_id}")
        shots.append(
            ShotBible(
                shot_id=item.shot_id,
                beat_id=item.beat_id,
                order=index + 1,
                scene_id=facts.scene_lock.scene_lock_id,
                duration_seconds=script.beats[index].duration_seconds,
                featured=[Featured.SUBJECT],
                opening_state=(
                    f"state_ref={transition.opening_state_id};"
                    f"pose_lock_id={facts.pose_lock.pose_lock_id}"
                ),
                visible_action=_visible_action(transition.event, item.creative_emphasis),
                closing_state=(
                    f"state_ref={transition.closing_state_id};"
                    f"pose_lock_id={facts.pose_lock.pose_lock_id}"
                ),
                camera_framing=item.camera_framing,
                camera_movement=CameraMovement.STATIC,
                handoff_to_next=Handoff.CONTINUOUS,
                risk_flags=[],
            )
        )

    roles = [BeatRole.HOOK, BeatRole.DEMO, BeatRole.CTA]
    return PetOnlyVideoBibleDraft(
        subject=SubjectIdentity(
            subject_id=facts.subject_lock.subject_id,
            kind="PET",
            species=facts.subject_lock.species,
            breed_or_type=facts.subject_lock.breed_or_type,
            coat_or_appearance=facts.subject_lock.coat_or_appearance,
            distinguishing_marks=facts.subject_lock.distinguishing_marks,
            identity_phrase=_identity_phrase(facts),
        ),
        scenes=[
            SceneSpec(
                scene_id=facts.scene_lock.scene_lock_id,
                environment_phrase=facts.scene_lock.environment,
                lighting_phrase=facts.scene_lock.lighting,
                palette=["source-locked"],
            )
        ],
        camera_rules=CameraRules(
            screen_direction="LEFT_TO_RIGHT", allowed_movements=[CameraMovement.STATIC]
        ),
        continuity_anchors=_continuity_anchors(facts),
        global_continuity_notes=[
            f"state_facts_digest={facts.facts_digest}",
            f"state_spine_digest={spine.spine_digest}",
        ],
        arc=[
            ArcBeat(beat_id=beat.beat_id, role=role)
            for beat, role in zip(script.beats, roles, strict=True)
        ],
        shots=shots,
        negative_concepts=[NegativeConcept.EXTRA_LIMBS, NegativeConcept.MORPHING],
        unverified_fields=[],
        needs_deep_ai=False,
        needs_human=False,
    )


def verify_compiled_shot_locks(
    bible: PetOnlyVideoBibleDraft, shot: ShotBible, facts: StateFactsV1
) -> tuple[str, ...]:
    """Verify the existing compiler projection contains every lock atom verbatim."""

    fields = expanded_shot_fields(bible, shot)
    flattened = canonical_json(fields).decode("utf-8")
    required = _required_lock_atoms(facts)
    return tuple(code for code, phrase in required.items() if phrase not in flattened)


def _required_lock_atoms(facts: StateFactsV1) -> dict[str, str]:
    required = {
        "SUBJECT_ID": facts.subject_lock.subject_id,
        "SPECIES": facts.subject_lock.species,
        "BREED_OR_TYPE": facts.subject_lock.breed_or_type,
        "COAT_OR_APPEARANCE": facts.subject_lock.coat_or_appearance,
        "BODY_POSE": facts.pose_lock.body_pose,
        "HEAD_DIRECTION": facts.pose_lock.head_direction,
        "SUPPORT_SURFACE": facts.pose_lock.support_surface,
        "ENVIRONMENT": facts.scene_lock.environment,
        "LIGHTING": facts.scene_lock.lighting,
        "CAMERA_MOVEMENT": "locked-off tripod camera, no camera movement",
        "ALLOWED_FRAMINGS": ", ".join(facts.camera_lock.allowed_framings),
    }
    for index, mark in enumerate(facts.subject_lock.distinguishing_marks):
        required[f"DISTINGUISHING_MARK_{index}"] = mark
    for index, accessory in enumerate(facts.scene_lock.temporary_accessories):
        required[f"TEMPORARY_ACCESSORY_{index}"] = accessory
    return required


def verify_shot_plan_prompt_locks(
    shot_plan: dict[str, Any], facts: StateFactsV1
) -> tuple[str, ...]:
    """Check every field consumed by the unchanged production positive-prompt compiler."""

    shots = shot_plan.get("shots")
    if not isinstance(shots, list) or len(shots) != 3:
        return ("PROMPT_LOCK_SHOT_PLAN_INVALID",)
    required = _required_lock_atoms(facts)
    findings: list[str] = []
    compiler_fields = (
        "subject",
        "environment",
        "action",
        "framing",
        "lighting_style",
        "continuity_keys",
        "required_facts",
    )
    for shot in shots:
        if not isinstance(shot, dict) or not isinstance(shot.get("shot_id"), str):
            return ("PROMPT_LOCK_SHOT_PLAN_INVALID",)
        flattened = canonical_json(
            {name: shot.get(name) for name in compiler_fields}
        ).decode("utf-8")
        findings.extend(
            f"PROMPT_LOCK_MISSING:{shot['shot_id']}:{code}"
            for code, phrase in required.items()
            if phrase not in flattened
        )
    return tuple(findings)


def bound_bible_integrity_findings(
    bible: PetOnlyVideoBibleDraft,
    facts: StateFactsV1,
    spine: StateSpineV1,
) -> tuple[str, ...]:
    """Check the *bound* Bible still carries the spine's actions, handoffs and prompt locks.

    Story acceptance (event sequence, framing progression, opt-in) is NOT decided here; that is
    the single policy in ``static_pet_story.evaluate_static_pet_story``.
    """

    findings: list[str] = []
    if spine.facts_digest != facts.facts_digest:
        return ("BOUND_BIBLE_FACTS_DIGEST_MISMATCH",)
    if len(bible.shots) != 3:
        return (*findings, "BOUND_BIBLE_SHOT_COUNT_INVALID")

    expected_action_phrases = (
        "makes one brief blink, and reopens both eyes",
        "only subtle breathing visible",
        "only subtle breathing visible",
    )
    for shot, transition, phrase in zip(
        bible.shots, spine.transitions, expected_action_phrases, strict=True
    ):
        if (
            shot.shot_id != transition.shot_id
            or phrase not in shot.visible_action
            or shot.duration_seconds != 4.0
        ):
            findings.append(f"BOUND_BIBLE_ACTION_MISMATCH:{shot.shot_id}")
        expected_opening = (
            f"state_ref={transition.opening_state_id};"
            f"pose_lock_id={facts.pose_lock.pose_lock_id}"
        )
        expected_closing = (
            f"state_ref={transition.closing_state_id};"
            f"pose_lock_id={facts.pose_lock.pose_lock_id}"
        )
        if shot.opening_state != expected_opening or shot.closing_state != expected_closing:
            findings.append(f"BOUND_BIBLE_STATE_HANDOFF_MISMATCH:{shot.shot_id}")
        if missing := verify_compiled_shot_locks(bible, shot, facts):
            findings.extend(
                f"BOUND_BIBLE_PROMPT_LOCK_MISSING:{shot.shot_id}:{code}"
                for code in missing
            )
    return tuple(findings)
