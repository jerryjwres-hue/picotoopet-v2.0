"""Versioned Video Bible (``video_bible.v1``): the Story Director's bounded, typed output.

The local model proposes a :class:`VideoBibleDraft`. Core validates it against the already
approved brief and script, binds it to the immutable source set, seals it with a content digest
and later derives the ``shot_plan.v1`` text fields from it deterministically, so subject and
product identity, scene lighting and camera rules are repeated verbatim in every shot instead of
being re-invented per shot.

Nothing here renders, scores or looks at a picture. A valid Bible is a statement about text.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from picotoopet_core.production.profile import (
    TIMELINE_TOLERANCE_SECONDS,
    VIDEO_OUTPUT_PROFILES,
    frame_count_for_duration,
)

from .models import CreativeBriefResult, CreativeScriptResult

VIDEO_BIBLE_SCHEMA_VERSION = "video_bible.v1"
MIN_SHOT_SECONDS = 2.0
MAX_BIBLE_SHOTS = 24
# Conservative bound under ProductionTaskPlan.positive_prompt (5000).
PROMPT_BUDGET_CHARS = 4500
_ID = r"^[A-Za-z0-9_.-]+$"
_Phrase = Annotated[str, Field(min_length=1, max_length=200)]


class CameraMovement(StrEnum):
    STATIC = "STATIC"
    SLOW_PUSH_IN = "SLOW_PUSH_IN"
    SLOW_PULL_OUT = "SLOW_PULL_OUT"
    PAN_LEFT = "PAN_LEFT"
    PAN_RIGHT = "PAN_RIGHT"
    TRACK_SIDE = "TRACK_SIDE"


CAMERA_PHRASE = {
    CameraMovement.STATIC: "locked-off tripod camera, no camera movement",
    CameraMovement.SLOW_PUSH_IN: "slow push-in",
    CameraMovement.SLOW_PULL_OUT: "slow pull-out",
    CameraMovement.PAN_LEFT: "slow pan left",
    CameraMovement.PAN_RIGHT: "slow pan right",
    CameraMovement.TRACK_SIDE: "side tracking shot",
}


class RiskFlag(StrEnum):
    COMPLEX_ANATOMY = "COMPLEX_ANATOMY"
    TEXT_IN_FRAME = "TEXT_IN_FRAME"
    FAST_MOTION = "FAST_MOTION"
    PRODUCT_CLOSEUP = "PRODUCT_CLOSEUP"
    LIQUID = "LIQUID"
    HAND_OBJECT = "HAND_OBJECT"


class NegativeConcept(StrEnum):
    """Advisory vocabulary for human reviewers; the executed negative prompt is Core-owned."""

    EXTRA_LIMBS = "EXTRA_LIMBS"
    MORPHING = "MORPHING"
    DUPLICATED_OBJECTS = "DUPLICATED_OBJECTS"
    TEXT_LOGO_WARP = "TEXT_LOGO_WARP"
    FLICKER = "FLICKER"


class Handoff(StrEnum):
    CONTINUOUS = "CONTINUOUS"
    CUT_ON_ACTION = "CUT_ON_ACTION"
    SCENE_CHANGE = "SCENE_CHANGE"


class BeatRole(StrEnum):
    HOOK = "HOOK"
    DEMO = "DEMO"
    PAYOFF = "PAYOFF"
    CTA = "CTA"
    BRIDGE = "BRIDGE"


class Featured(StrEnum):
    SUBJECT = "SUBJECT"
    PRODUCT = "PRODUCT"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SubjectIdentity(_Strict):
    subject_id: str = Field(pattern=_ID, max_length=80)
    kind: Literal["PET", "PERSON"]
    species: str = Field(min_length=1, max_length=80)
    breed_or_type: str = Field(min_length=1, max_length=120)
    coat_or_appearance: str = Field(min_length=1, max_length=240)
    distinguishing_marks: list[str] = Field(default_factory=list, max_length=8)
    # Appears verbatim in the subject of every shot that features the subject.
    identity_phrase: str = Field(min_length=1, max_length=240)


class BibleClaim(_Strict):
    claim_id: str = Field(pattern=_ID, max_length=80)
    text: str = Field(min_length=1, max_length=300)
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)
    verified: bool

    @model_validator(mode="after")
    def _verified_needs_evidence(self) -> BibleClaim:
        if self.verified and not self.evidence_ids:
            raise ValueError("verified claim must cite evidence")
        return self


class ProductIdentity(_Strict):
    product_id: str = Field(pattern=_ID, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=120)
    shape_color_material: str = Field(min_length=1, max_length=240)
    identity_phrase: str = Field(min_length=1, max_length=240)
    # Readable text and logos are the least reliable thing a T2V model draws.
    logo_policy: Literal["NO_TEXT_OR_LOGO_IN_FRAME", "OVERLAY_ONLY"] = "NO_TEXT_OR_LOGO_IN_FRAME"
    claims: list[BibleClaim] = Field(default_factory=list, max_length=12)


class SceneSpec(_Strict):
    scene_id: str = Field(pattern=_ID, max_length=80)
    environment_phrase: str = Field(min_length=1, max_length=300)
    lighting_phrase: str = Field(min_length=1, max_length=200)
    palette: list[str] = Field(min_length=1, max_length=6)


class CameraRules(_Strict):
    screen_direction: Literal["LEFT_TO_RIGHT", "RIGHT_TO_LEFT", "NONE"] = "NONE"
    allowed_movements: list[CameraMovement] = Field(min_length=1, max_length=6)


class ArcBeat(_Strict):
    beat_id: str = Field(pattern=_ID, max_length=80)
    role: BeatRole


class ShotBible(_Strict):
    shot_id: str = Field(pattern=_ID, max_length=80)
    beat_id: str = Field(pattern=_ID, max_length=80)
    order: int = Field(ge=1, le=200)
    scene_id: str = Field(pattern=_ID, max_length=80)
    duration_seconds: float = Field(gt=0.0, le=120.0)
    featured: list[Featured] = Field(min_length=1, max_length=2)
    opening_state: str = Field(min_length=1, max_length=300)
    visible_action: str = Field(min_length=1, max_length=400)
    closing_state: str = Field(min_length=1, max_length=300)
    camera_framing: str = Field(min_length=1, max_length=120)
    camera_movement: CameraMovement
    handoff_to_next: Handoff
    risk_flags: list[RiskFlag] = Field(default_factory=list, max_length=6)


class VideoBibleDraft(_Strict):
    """What the local model may emit. Core-owned binding fields are deliberately absent."""

    schema_version: Literal["video_bible.v1"] = VIDEO_BIBLE_SCHEMA_VERSION
    subject: SubjectIdentity
    product: ProductIdentity
    scenes: list[SceneSpec] = Field(min_length=1, max_length=8)
    camera_rules: CameraRules
    continuity_anchors: list[_Phrase] = Field(min_length=1, max_length=8)
    global_continuity_notes: list[_Phrase] = Field(default_factory=list, max_length=8)
    arc: list[ArcBeat] = Field(min_length=1, max_length=60)
    shots: list[ShotBible] = Field(min_length=1, max_length=MAX_BIBLE_SHOTS)
    negative_concepts: list[NegativeConcept] = Field(default_factory=list, max_length=5)
    unverified_fields: list[str] = Field(default_factory=list, max_length=20)
    needs_deep_ai: bool = False
    needs_human: bool = False


class VideoBible(VideoBibleDraft):
    """Sealed, source-bound Bible persisted as ``stage_results["video_bible.v1"]``."""

    bible_id: str = Field(pattern=_ID, max_length=80)
    goal_id: str = Field(min_length=1, max_length=120)
    source_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_idea_id: str = Field(min_length=1, max_length=80)
    bible_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _digest_matches_content(self) -> VideoBible:
        if self.bible_digest != compute_bible_digest(self.model_dump(mode="json")):
            raise ValueError("bible_digest does not match content")
        return self


def compute_bible_digest(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "bible_digest"}
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def seal_bible(
    draft: VideoBibleDraft,
    *,
    project_key: str,
    source_set_digest: str,
    selected_idea_id: str,
) -> VideoBible:
    body = draft.model_dump(mode="json")
    body["bible_id"] = (
        "vb-" + hashlib.sha256(f"{source_set_digest}|{selected_idea_id}".encode()).hexdigest()[:16]
    )
    body["goal_id"] = project_key[:120]
    body["source_set_digest"] = source_set_digest
    body["selected_idea_id"] = selected_idea_id
    body["bible_digest"] = compute_bible_digest(body)
    return VideoBible.model_validate(body)


# ── Validation against the approved brief and script ───────────────────────────────────


@dataclass(frozen=True)
class BibleFinding:
    code: str
    shot_id: str | None = None
    detail: str = ""
    # Path-like or forbidden text is rejected outright; everything else is correctable.
    reject: bool = False


_PATH_LIKE = re.compile(
    r"[A-Za-z]:\\|\\\\|(?:^|\s)(?:\.{1,2}/|~/|/[A-Za-z0-9_.-]+/)"
    r"|\.(?:png|jpe?g|webp|gif|mp4|mov|webm)\b",
    re.IGNORECASE,
)
_HYPE = re.compile(
    r"\b(?:8k|4k|masterpiece|cinematic|best quality|trending on|hyper-?realistic|"
    r"award-winning|ultra[- ](?:hd|realistic|detailed))\b",
    re.IGNORECASE,
)
_MULTI_STEP = re.compile(r"(?:\bthen\b|;|；|然后)", re.IGNORECASE)


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def expanded_shot_fields(bible: VideoBibleDraft, shot: ShotBible) -> dict[str, Any]:
    """The only ShotPlanItem text a Bible may influence. No new key is ever added."""

    scene = next(item for item in bible.scenes if item.scene_id == shot.scene_id)
    featured: list[str] = []
    if Featured.SUBJECT in shot.featured:
        featured.append(bible.subject.identity_phrase)
    if Featured.PRODUCT in shot.featured:
        featured.append(bible.product.identity_phrase)
    return {
        "subject": ", ".join(featured),
        "environment": scene.environment_phrase,
        "action": (
            f"{shot.visible_action}; opens on {shot.opening_state}; ends on {shot.closing_state}"
        ),
        "framing": f"{shot.camera_framing}, {CAMERA_PHRASE[shot.camera_movement]}",
        "lighting_style": scene.lighting_phrase,
        "continuity_keys": [*bible.continuity_anchors, *bible.global_continuity_notes],
    }


def evaluate_video_bible(
    draft: VideoBibleDraft,
    *,
    brief: CreativeBriefResult,
    script: CreativeScriptResult,
    evidence_ids: set[str],
    required_shot_count: int | None = None,
) -> list[BibleFinding]:
    findings: list[BibleFinding] = []

    def add(code: str, shot_id: str | None = None, detail: str = "", reject: bool = False) -> None:
        findings.append(BibleFinding(code, shot_id, detail, reject))

    payload = draft.model_dump(mode="json")
    strings = _strings(payload)
    if any(_PATH_LIKE.search(text) for text in strings):
        add("BIBLE_PATH_LIKE", detail="paths and media file names are never inputs", reject=True)
    if any(_HYPE.search(text) for text in strings):
        add("QUALITY_ADJECTIVE_SPAM", detail="replace with concrete visible attributes")

    # Story spine: arc == approved script beats, HOOK first, one CTA last.
    script_ids = [beat.beat_id for beat in script.beats]
    if [item.beat_id for item in draft.arc] != script_ids:
        add("ARC_MISMATCH", detail="arc must list exactly the supplied beat_ids in order")
    roles = [item.role for item in draft.arc]
    if (
        roles[0] is not BeatRole.HOOK
        or roles[-1] is not BeatRole.CTA
        or roles.count(BeatRole.CTA) != 1
        or draft.arc[-1].beat_id != script.cta_beat_id
    ):
        add("ARC_ROLE_ORDER", detail="first beat HOOK, last beat the single CTA")

    # Identity phrases must be concrete and anchored in the declared subject.
    subject = draft.subject
    if len(subject.identity_phrase.split()) < 4:
        add("IDENTITY_PHRASE_TOO_VAGUE", detail="subject.identity_phrase")
    phrase = subject.identity_phrase.casefold()
    if subject.breed_or_type.casefold() not in phrase and subject.species.casefold() not in phrase:
        add("IDENTITY_PHRASE_OFF_SUBJECT", detail="must name the species or breed")
    if len(draft.product.identity_phrase.split()) < 4:
        add("IDENTITY_PHRASE_TOO_VAGUE", detail="product.identity_phrase")

    # Claims: evidence must exist and unverified claims may never be spoken.
    spoken = " ".join(_norm(beat.voiceover) for beat in script.beats if beat.voiceover)
    for claim in draft.product.claims:
        if not set(claim.evidence_ids) <= evidence_ids:
            add("CLAIM_UNKNOWN_EVIDENCE", detail=claim.claim_id)
        if not claim.verified and _norm(claim.text) in spoken:
            add("CLAIM_UNVERIFIED_IN_VOICEOVER", detail=claim.claim_id)

    # Shots.
    fps = VIDEO_OUTPUT_PROFILES[brief.output_profile_id].fps
    scene_ids = {item.scene_id for item in draft.scenes}
    shots = draft.shots
    if [item.order for item in shots] != list(range(1, len(shots) + 1)) or len(
        {item.shot_id for item in shots}
    ) != len(shots):
        add("SHOT_ORDER_INVALID", detail="orders must be 1..n and shot_ids unique")
    beat_position = {beat_id: index for index, beat_id in enumerate(script_ids)}
    positions = [beat_position.get(item.beat_id, -1) for item in shots]
    if -1 in positions:
        add("SHOT_UNKNOWN_BEAT", detail="shot.beat_id must be a supplied beat_id")
    elif positions != sorted(positions):
        add("SHOT_BEAT_ORDER", detail="shots must follow the script beat order")
    elif set(script_ids) - {item.beat_id for item in shots}:
        add("SCRIPT_BEAT_NOT_COVERED", detail="every script beat needs at least one shot")
    total = sum(item.duration_seconds for item in shots)
    if abs(total - script.target_duration_seconds) > TIMELINE_TOLERANCE_SECONDS:
        add(
            "TIMELINE_MISMATCH",
            detail=f"shots total {total:g}s vs script {script.target_duration_seconds:g}s",
        )
    if required_shot_count is not None and len(shots) != required_shot_count:
        add(
            "SHOT_COUNT_MISMATCH",
            detail=f"the goal requires exactly {required_shot_count} shots, got {len(shots)}",
        )
    if required_shot_count is not None and required_shot_count >= 2:
        _multi_shot_findings(draft, add)
    if not any(Featured.PRODUCT in item.featured for item in shots):
        add("PRODUCT_NEVER_FEATURED", detail="at least one shot must feature the product")

    brief_notes = ", ".join(brief.continuity_notes)
    for index, shot in enumerate(shots):
        sid = shot.shot_id
        if shot.scene_id not in scene_ids:
            add("SCENE_UNKNOWN", sid)
            continue
        if shot.camera_movement not in draft.camera_rules.allowed_movements:
            add("CAMERA_RULE_VIOLATION", sid)
        try:
            frame_count_for_duration(shot.duration_seconds, fps)
        except ValueError:
            add("SHOT_DURATION_UNRENDERABLE", sid, "split into shots of 2.0-5.0 seconds")
        else:
            if shot.duration_seconds < MIN_SHOT_SECONDS:
                add("SHOT_DURATION_TOO_SHORT", sid, "use at least 2.0 seconds")
        if _MULTI_STEP.search(shot.visible_action):
            add("ACTION_MULTI_STEP", sid, "one dominant action; split into adjacent shots")
        if (
            RiskFlag.TEXT_IN_FRAME in shot.risk_flags
            and draft.product.logo_policy == "NO_TEXT_OR_LOGO_IN_FRAME"
        ):
            add("TEXT_IN_FRAME_CONTRADICTION", sid)
        following = shots[index + 1] if index + 1 < len(shots) else None
        if (
            following is not None
            and shot.handoff_to_next is Handoff.CONTINUOUS
            and _norm(shot.closing_state) != _norm(following.opening_state)
        ):
            add("HANDOFF_BROKEN", sid, "closing_state must equal the next opening_state")
        fields = expanded_shot_fields(draft, shot)
        estimate = sum(len(str(fields[key])) for key in fields if key != "continuity_keys")
        estimate += len(", ".join(fields["continuity_keys"])) + len(brief_notes) + 120
        if estimate > PROMPT_BUDGET_CHARS:
            add("PROMPT_TOO_LONG", sid, "shorten identity, scene and action phrases")
    return findings


def _multi_shot_findings(draft: VideoBibleDraft, add) -> None:  # type: ignore[no-untyped-def]
    """Cross-shot identity and prompt hygiene for an explicit multi-shot Goal."""

    from .director import actions_too_similar, negative_conflicts

    if len(draft.continuity_anchors) + len(draft.global_continuity_notes) < 2:
        add(
            "CONTINUITY_ANCHORS_TOO_FEW",
            detail="give at least 2 identity/scene anchors; they are repeated in every shot",
        )
    for index, first in enumerate(draft.shots):
        for second in draft.shots[index + 1 :]:
            if actions_too_similar(first.visible_action, second.visible_action):
                add(
                    "SHOT_ACTIONS_NOT_DISTINCT",
                    first.shot_id,
                    f"{first.shot_id} and {second.shot_id} describe the same action",
                )
    texts = [
        draft.subject.identity_phrase, draft.product.identity_phrase,
        *draft.continuity_anchors, *draft.global_continuity_notes,
        *(item.environment_phrase for item in draft.scenes),
        *(item.lighting_phrase for item in draft.scenes),
        *(item.visible_action for item in draft.shots),
        *(item.opening_state for item in draft.shots),
        *(item.closing_state for item in draft.shots),
        *(item.camera_framing for item in draft.shots),
    ]
    clashing = negative_conflicts(texts)
    if clashing:
        add(
            "PROMPT_CONTRADICTS_NEGATIVE",
            detail="avoid these words, the sampler is told to avoid them: " + ", ".join(clashing),
        )


def correction_for(findings: list[BibleFinding]) -> str:
    """Bounded repair instruction for the single local retry (adapter caps it at 2000)."""

    parts = [
        f"{item.code}" + (f"({item.shot_id})" if item.shot_id else "")
        + (f": {item.detail}" if item.detail else "")
        for item in findings[:12]
    ]
    return "Repair only these video_bible.v1 defects and keep everything else: " + "; ".join(parts)


# ── Deterministic derivation of the existing shot_plan.v1 ──────────────────────────────


def derive_shot_plan(bible: VideoBible, script: CreativeScriptResult) -> dict[str, Any]:
    """Build a plain ``ShotPlanResult`` payload from the sealed Bible.

    Renderer-neutral, ``GENERATIVE_VIDEO`` only: the local runtime holds no approved image, so it
    never emits ``IMAGE_TO_VIDEO``, a reference, or an asset path.
    """

    evidence_by_beat = {beat.beat_id: list(beat.claim_source_evidence_ids) for beat in script.beats}
    shots: list[dict[str, Any]] = []
    for shot in bible.shots:
        risks = ",".join(flag.value for flag in shot.risk_flags) or "none"
        shots.append(
            {
                "shot_id": shot.shot_id,
                "beat_id": shot.beat_id,
                "order": shot.order,
                "duration_seconds": shot.duration_seconds,
                **expanded_shot_fields(bible, shot),
                "required_facts": [],
                "source_evidence_ids": evidence_by_beat.get(shot.beat_id, []),
                "text_reference": None,
                "production_notes": (
                    f"renderer-neutral; video_bible={bible.bible_digest[:16]}; risk_flags={risks}"
                ),
                "render_intent": "GENERATIVE_VIDEO",
            }
        )
    return {
        "schema_version": "1.0",
        "creative_profile": "creative.content_plan.v1",
        "shots": shots,
        "warnings": [],
        "needs_deep_ai": False,
        "needs_human": False,
    }
