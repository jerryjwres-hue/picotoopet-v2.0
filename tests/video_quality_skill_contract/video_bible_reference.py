"""Executable reference for the Video Bible sidecar contract (video_bible.v1).

This module is a TEST-SIDE specification, not production code. G006 can lift it into
``src/picotoopet_core/creative`` once the contract is accepted. It maps onto the existing
Core models (CreativeBriefResult / CreativeScriptResult / ShotPlanItem / ProductionTaskPlan)
without adding any field to them, and it never claims visual quality: every report carries
``visual_qa == "UNVERIFIED"``.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from picotoopet_core.creative.models import (
    CreativeBriefResult,
    CreativeRenderIntent,
    CreativeScriptResult,
    ShotPlanResult,
)
from picotoopet_core.creative.quality import CreativeQualityGate
from picotoopet_core.production.profile import (
    ALLOWED_WORKFLOW_IDS,
    I2V_WORKFLOW_ID,
    T2V_WORKFLOW_ID,
    VIDEO_OUTPUT_PROFILES,
    frame_count_for_duration,
)

SCHEMA_VERSION = "video_bible.v1"
PREFERRED_SHOT_SECONDS = (3.0, 5.0)
_ID = r"^[A-Za-z0-9_.-]+$"
_SHA256 = r"^[0-9a-f]{64}$"


# ── Text normalisation (deterministic, idempotent) ─────────────────────────────────────


def normalize_instruction(text: str) -> str:
    """NFKC, drop control chars, collapse all whitespace. Same input -> same bytes."""

    folded = unicodedata.normalize("NFKC", text)
    cleaned = "".join(
        " " if unicodedata.category(ch) in {"Cc", "Cf", "Zs", "Zl", "Zp"} else ch for ch in folded
    )
    result = " ".join(cleaned.split())
    if not result:
        raise ValueError("EMPTY_INSTRUCTION")
    return result


# ── Closed vocabularies ────────────────────────────────────────────────────────────────


class CameraMovement(StrEnum):
    STATIC = "STATIC"
    SLOW_PUSH_IN = "SLOW_PUSH_IN"
    SLOW_PULL_OUT = "SLOW_PULL_OUT"
    PAN_LEFT = "PAN_LEFT"
    PAN_RIGHT = "PAN_RIGHT"
    TRACK_SIDE = "TRACK_SIDE"


CAMERA_PHRASE = {
    CameraMovement.STATIC: "static camera",
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
    """Advisory only. The executed negative prompt is the compiler-owned policy."""

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


class RightsSource(StrEnum):
    USER_SUPPLIED = "USER_SUPPLIED"
    LICENSED = "LICENSED"
    GENERATED_BY_PICOTOOPET = "GENERATED_BY_PICOTOOPET"


# ── Contract models ────────────────────────────────────────────────────────────────────


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SubjectIdentity(_Strict):
    subject_id: str = Field(pattern=_ID, max_length=80)
    kind: Literal["PET", "PERSON"]
    species: str = Field(min_length=1, max_length=80)
    breed_or_type: str = Field(min_length=1, max_length=120)
    coat_or_appearance: str = Field(min_length=1, max_length=240)
    distinguishing_marks: list[str] = Field(default_factory=list, max_length=8)
    # Appears verbatim in every featured shot's ShotPlanItem.subject.
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
    # Text/logos are the least reliable thing a T2V model draws: default is "never in-frame".
    logo_policy: Literal["NO_TEXT_OR_LOGO_IN_FRAME", "OVERLAY_ONLY"] = "NO_TEXT_OR_LOGO_IN_FRAME"
    claims: list[BibleClaim] = Field(default_factory=list, max_length=12)


class SceneSpec(_Strict):
    scene_id: str = Field(pattern=_ID, max_length=80)
    environment_phrase: str = Field(min_length=1, max_length=300)
    lighting_phrase: str = Field(min_length=1, max_length=200)
    palette: list[str] = Field(min_length=1, max_length=6)


class CameraRules(_Strict):
    screen_direction: Literal["LEFT_TO_RIGHT", "RIGHT_TO_LEFT", "NONE"] = "NONE"
    allowed_movements: list[CameraMovement] = Field(min_length=1)


class ReferenceAsset(_Strict):
    """Present only when a reference is verified; never a path (the digest is the identity)."""

    reference_id: str = Field(pattern=_ID, max_length=80)
    sha256: str = Field(pattern=_SHA256)
    rights_source: RightsSource
    verified: Literal[True]


class ArcBeat(_Strict):
    beat_id: str = Field(pattern=_ID, max_length=80)
    role: BeatRole


class ShotBible(_Strict):
    shot_id: str = Field(pattern=_ID, max_length=80)
    beat_id: str = Field(pattern=_ID, max_length=80)
    order: int = Field(ge=1, le=200)
    scene_id: str = Field(pattern=_ID, max_length=80)
    duration_seconds: float = Field(gt=0.0, le=120.0)
    featured: list[Featured] = Field(min_length=1)
    opening_state: str = Field(min_length=1, max_length=300)
    visible_action: str = Field(min_length=1, max_length=400)
    closing_state: str = Field(min_length=1, max_length=300)
    camera_framing: str = Field(min_length=1, max_length=120)
    camera_movement: CameraMovement
    handoff_to_next: Handoff
    risk_flags: list[RiskFlag] = Field(default_factory=list, max_length=6)
    uses_reference: bool = False


class VideoBible(_Strict):
    schema_version: Literal["video_bible.v1"] = SCHEMA_VERSION
    bible_id: str = Field(pattern=_ID, max_length=80)
    goal_id: str = Field(min_length=1, max_length=120)
    source_set_digest: str = Field(pattern=_SHA256)
    selected_idea_id: str = Field(min_length=1, max_length=80)
    subject: SubjectIdentity
    product: ProductIdentity
    scenes: list[SceneSpec] = Field(min_length=1, max_length=8)
    camera_rules: CameraRules
    continuity_anchors: list[str] = Field(min_length=1, max_length=8)
    global_continuity_notes: list[str] = Field(default_factory=list, max_length=8)
    reference: ReferenceAsset | None = None
    arc: list[ArcBeat] = Field(min_length=1, max_length=60)
    shots: list[ShotBible] = Field(min_length=1, max_length=120)
    negative_concepts: list[NegativeConcept] = Field(default_factory=list, max_length=5)
    unverified_fields: list[str] = Field(default_factory=list, max_length=20)
    bible_digest: str | None = Field(default=None, pattern=_SHA256)

    @model_validator(mode="after")
    def _digest_matches_content(self) -> VideoBible:
        if self.bible_digest is not None and self.bible_digest != compute_digest(self):
            raise ValueError("bible_digest does not match content")
        return self

    def sealed(self) -> VideoBible:
        return self.model_copy(update={"bible_digest": compute_digest(self)})


def compute_digest(bible: VideoBible) -> str:
    payload = bible.model_dump(mode="json", exclude={"bible_digest"})
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Deterministic expansion Bible -> existing ShotPlanItem text fields ─────────────────


def expand_shot_fields(bible: VideoBible, shot: ShotBible) -> dict[str, Any]:
    """The only fields a Bible may influence. No new key reaches ShotPlanItem."""

    scene = next(item for item in bible.scenes if item.scene_id == shot.scene_id)
    return {
        "subject": ", ".join(_featured_phrases(bible, shot)),
        "environment": scene.environment_phrase,
        "action": f"{shot.visible_action}; opens on {shot.opening_state}; "
        f"ends on {shot.closing_state}",
        "framing": f"{shot.camera_framing}, {CAMERA_PHRASE[shot.camera_movement]}",
        "lighting_style": scene.lighting_phrase,
        "continuity_keys": list(bible.continuity_anchors),
    }


def _featured_phrases(bible: VideoBible, shot: ShotBible) -> list[str]:
    phrases: list[str] = []
    if Featured.SUBJECT in shot.featured:
        phrases.append(bible.subject.identity_phrase)
    if Featured.PRODUCT in shot.featured:
        phrases.append(bible.product.identity_phrase)
    return phrases


def expected_core_prompt(shot: dict[str, Any], brief_notes: list[str]) -> str:
    """What compile_production_plan builds today (wan22-shot-prompt-v1.1.0), re-stated.

    Tests pin this against the real compiler so drift in either place is caught.
    """

    notes = [note.strip() for note in brief_notes if note.strip()]
    keys = ", ".join(str(item) for item in shot.get("continuity_keys", []) if str(item).strip())
    facts = ", ".join(str(item) for item in shot.get("required_facts", []) if str(item).strip())
    segments = [
        str(shot.get("subject", "")).strip(),
        "wan22-shot-prompt-v1.1.0 story continuity: " + ", ".join(notes) if notes else "",
        str(shot.get("environment", "")).strip(),
        str(shot.get("action", "")).strip(),
        str(shot.get("framing", "")).strip(),
        str(shot.get("lighting_style", "")).strip(),
        keys,
        facts,
    ]
    return "; ".join(segment for segment in segments if segment)


# ── Lint: Bible vs the Creative stage outputs ──────────────────────────────────────────


class Severity(StrEnum):
    REVIEW = "REVIEW"
    RETRY_CREATIVE = "RETRY_CREATIVE"
    BLOCKED = "BLOCKED"


_RANK = {Severity.REVIEW: 1, Severity.RETRY_CREATIVE: 2, Severity.BLOCKED: 3}


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    shot_id: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class BibleReport:
    verdict: Literal["OK", "REVIEW", "RETRY_CREATIVE", "BLOCKED"]
    findings: tuple[Finding, ...]
    human_review_focus: tuple[str, ...] = field(default_factory=tuple)
    # A structurally OK bible says nothing about pixels.
    visual_qa: Literal["UNVERIFIED"] = "UNVERIFIED"

    @property
    def codes(self) -> list[str]:
        return [item.code for item in self.findings]


_PATH_LIKE = re.compile(
    r"[A-Za-z]:\\|\\\\|(?:^|\s)(?:\.{1,2}/|~/|/[A-Za-z0-9_.-]+/)"
    r"|\.(?:png|jpe?g|webp|gif|mp4|mov|webm)\b",
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


def lint_bible(
    bible: VideoBible,
    *,
    brief: dict[str, Any],
    script: dict[str, Any],
    shot_plan: dict[str, Any],
    evidence_ids: set[str],
    source_set_digest: str,
    trusted_assets: dict[str, str] | None = None,
) -> BibleReport:
    findings: list[Finding] = []

    def add(code: str, severity: Severity, shot_id: str | None = None, detail: str = "") -> None:
        findings.append(Finding(code, severity, shot_id, detail))

    try:
        brief_model = CreativeBriefResult.model_validate(brief)
        script_model = CreativeScriptResult.model_validate(script)
        plan_model = ShotPlanResult.model_validate(shot_plan)
    except ValidationError:
        add("CREATIVE_STAGE_SCHEMA_INVALID", Severity.BLOCKED)
        return _report(findings, bible)

    payload = bible.model_dump(mode="json")
    if CreativeQualityGate.contains_forbidden_output(payload):
        add("BIBLE_FORBIDDEN_PAYLOAD", Severity.BLOCKED)
    if any(_PATH_LIKE.search(text) for text in _strings(payload) + _strings(shot_plan)):
        add("BIBLE_PATH_LIKE", Severity.BLOCKED, detail="paths/media names are never inputs")

    if bible.source_set_digest != source_set_digest:
        add("BIBLE_SOURCE_BINDING_MISMATCH", Severity.BLOCKED)
    if bible.selected_idea_id != brief_model.selected_idea_id:
        add("BIBLE_IDEA_MISMATCH", Severity.BLOCKED)

    # Arc must be exactly the approved script beats.
    if [b.beat_id for b in bible.arc] != [b.beat_id for b in script_model.beats]:
        add("ARC_MISMATCH", Severity.BLOCKED)
    cta_roles = [b.beat_id for b in bible.arc if b.role is BeatRole.CTA]
    if cta_roles != [script_model.cta_beat_id]:
        add("ARC_CTA_MISMATCH", Severity.BLOCKED)

    # Global notes must reach the brief, because that is the only brief field Core compiles.
    missing_notes = [
        note for note in bible.global_continuity_notes
        if note not in brief_model.continuity_notes
    ]
    if missing_notes:
        add("BRIEF_CONTINUITY_NOTES_MISSING", Severity.RETRY_CREATIVE, detail=missing_notes[0])

    # Claims: evidence must exist; unverified claims may never be spoken.
    voiceovers = [b.voiceover for b in script_model.beats if b.voiceover]
    for claim in bible.product.claims:
        if not set(claim.evidence_ids) <= evidence_ids:
            add("CLAIM_UNKNOWN_EVIDENCE", Severity.BLOCKED, detail=claim.claim_id)
        if not claim.verified and any(claim.text.lower() in v.lower() for v in voiceovers):
            add("CLAIM_UNVERIFIED_IN_VOICEOVER", Severity.BLOCKED, detail=claim.claim_id)
    for beat in script_model.beats:
        if beat.voiceover and not beat.claim_source_evidence_ids:
            add("VOICEOVER_UNCITED", Severity.REVIEW, detail=beat.beat_id)

    # Handoffs inside the Bible itself.
    for current, following in zip(bible.shots, bible.shots[1:], strict=False):
        if (
            current.handoff_to_next is Handoff.CONTINUOUS
            and current.closing_state != following.opening_state
        ):
            add("HANDOFF_BROKEN", Severity.RETRY_CREATIVE, current.shot_id)

    # Shot set equality and per-shot field containment.
    if [(s.shot_id, s.beat_id, s.order, s.duration_seconds) for s in bible.shots] != [
        (s.shot_id, s.beat_id, s.order, s.duration_seconds) for s in plan_model.shots
    ]:
        add("SHOT_SET_MISMATCH", Severity.BLOCKED)
        return _report(findings, bible)

    fps = VIDEO_OUTPUT_PROFILES[brief_model.output_profile_id].fps
    scenes = {s.scene_id: s for s in bible.scenes}
    focus: list[str] = []
    for bshot, shot in zip(bible.shots, plan_model.shots, strict=True):
        sid = shot.shot_id
        scene = scenes.get(bshot.scene_id)
        if scene is None:
            add("SCENE_UNKNOWN", Severity.BLOCKED, sid)
            continue
        want = expand_shot_fields(bible, bshot)
        if bshot.camera_movement not in bible.camera_rules.allowed_movements:
            add("CAMERA_RULE_VIOLATION", Severity.RETRY_CREATIVE, sid)
        checks = (
            ("subject", shot.subject, _featured_phrases(bible, bshot)),
            ("environment", shot.environment, [want["environment"]]),
            ("action", shot.action, [bshot.visible_action]),
            ("framing", shot.framing, [bshot.camera_framing, CAMERA_PHRASE[bshot.camera_movement]]),
            ("lighting_style", shot.lighting_style, [want["lighting_style"]]),
        )
        for name, actual, needles in checks:
            for needle in needles:
                if needle not in actual:
                    add("SHOT_FIELD_DRIFT", Severity.RETRY_CREATIVE, sid, name)
        if not set(bible.continuity_anchors) <= set(shot.continuity_keys):
            add("CONTINUITY_ANCHOR_MISSING", Severity.RETRY_CREATIVE, sid)
        if _MULTI_STEP.search(bshot.visible_action):
            add("ACTION_MULTI_STEP", Severity.REVIEW, sid, "split into adjacent shots")
        try:
            frame_count_for_duration(shot.duration_seconds, fps)
        except ValueError:
            add("SHOT_DURATION_UNRENDERABLE", Severity.RETRY_CREATIVE, sid, "split the beat")
        else:
            low, high = PREFERRED_SHOT_SECONDS
            if not low <= shot.duration_seconds <= high:
                add("SHOT_DURATION_OFF_BAND", Severity.REVIEW, sid)
        if (
            RiskFlag.TEXT_IN_FRAME in bshot.risk_flags
            and bible.product.logo_policy == "NO_TEXT_OR_LOGO_IN_FRAME"
        ):
            add("TEXT_IN_FRAME_CONTRADICTION", Severity.RETRY_CREATIVE, sid)
        wants_reference = bshot.uses_reference or (
            shot.render_intent is CreativeRenderIntent.IMAGE_TO_VIDEO
        )
        if wants_reference and (bible.reference is None or not (trusted_assets or {}).get(sid)):
            add("REFERENCE_UNAVAILABLE", Severity.BLOCKED, sid)
        focus.extend(f"{sid}:{flag.value}" for flag in bshot.risk_flags)
    return _report(findings, bible, tuple(focus))


def _report(
    findings: list[Finding], bible: VideoBible, focus: tuple[str, ...] = ()
) -> BibleReport:
    verdict: Literal["OK", "REVIEW", "RETRY_CREATIVE", "BLOCKED"] = "OK"
    if findings:
        top = max(findings, key=lambda item: _RANK[item.severity])
        verdict = top.severity.value  # type: ignore[assignment]
    return BibleReport(verdict, tuple(findings), focus)


# ── Model adapters: non-interchangeable, only Wan2.2 T2V is executable today ───────────


class AdapterStatus(StrEnum):
    PRODUCTION = "PRODUCTION"
    FUTURE_GATED = "FUTURE_GATED"
    EVALUATION_ONLY = "EVALUATION_ONLY"


@dataclass(frozen=True)
class ModelAdapter:
    adapter_id: str
    status: AdapterStatus
    workflow_id: str | None
    required_inputs: tuple[str, ...]
    executable_by_core: bool


ADAPTERS = {
    "wan22_ti2v5b_t2v": ModelAdapter(
        "wan22_ti2v5b_t2v", AdapterStatus.PRODUCTION, T2V_WORKFLOW_ID, ("text",), True
    ),
    "wan22_ti2v5b_i2v": ModelAdapter(
        "wan22_ti2v5b_i2v",
        AdapterStatus.FUTURE_GATED,
        I2V_WORKFLOW_ID,
        ("text", "trusted_reference_sha256"),
        False,
    ),
    "wan21_vace": ModelAdapter(
        "wan21_vace",
        AdapterStatus.EVALUATION_ONLY,
        None,
        ("text", "src_ref_images", "optional:src_video", "optional:src_mask"),
        False,
    ),
    "hunyuanvideo_15": ModelAdapter(
        "hunyuanvideo_15", AdapterStatus.EVALUATION_ONLY, None, ("text",), False
    ),
    "ltx_video": ModelAdapter(
        "ltx_video", AdapterStatus.EVALUATION_ONLY, None, ("text",), False
    ),
}


class PromptReview(_Strict):
    """Proposal only. ProductionTaskPlan.positive_prompt stays compiler-owned."""

    shot_id: str
    adapter_id: str
    target_workflow_id: str | None
    positive_prompt: str = Field(min_length=1, max_length=5000)
    suggested_negative_concepts: list[NegativeConcept]
    reference_asset_sha256: str | None
    requires_approval: bool
    visual_qa: Literal["UNVERIFIED"] = "UNVERIFIED"


def prompt_review(
    bible: VideoBible, shot: dict[str, Any], brief_notes: list[str], adapter_id: str
) -> PromptReview:
    adapter = ADAPTERS[adapter_id]
    if adapter.status is AdapterStatus.EVALUATION_ONLY:
        raise ValueError("ADAPTER_EVALUATION_ONLY")
    prompt = normalize_instruction(expected_core_prompt(shot, brief_notes))
    needs_reference = "trusted_reference_sha256" in adapter.required_inputs
    if needs_reference and bible.reference is None:
        raise ValueError("REFERENCE_UNAVAILABLE")
    assert adapter.workflow_id in ALLOWED_WORKFLOW_IDS
    return PromptReview(
        shot_id=str(shot["shot_id"]),
        adapter_id=adapter_id,
        target_workflow_id=adapter.workflow_id,
        positive_prompt=prompt,
        suggested_negative_concepts=list(bible.negative_concepts),
        reference_asset_sha256=(
            bible.reference.sha256 if needs_reference and bible.reference else None
        ),
        requires_approval=not adapter.executable_by_core,
    )
