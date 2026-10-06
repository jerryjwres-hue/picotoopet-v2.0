"""C008A: deterministic caption/overlay plan derived from Creative + Production facts.

TEXT_CARD remains a full Production shot. This module plans only post-production text
presentation over an existing video timeline. Captions intentionally remain empty until
a future trusted transcript contract exists.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from picotoopet_core.creative.models import (
    CreativeScriptResult,
    ShotPlanResult,
    VideoOutputProfile,
)
from picotoopet_core.production.models import ProductionPlan

CAPTION_STYLE_PROFILE_ID = "caption.lower-third.v1"
OVERLAY_STYLE_PROFILE_ID = "overlay.title-safe.v1"
FONT_PROFILE_ID = "font.windows-system-sans.v1"

NOT_READY = "TEXT_PRESENTATION_NOT_READY"
SOURCE_MISMATCH = "TEXT_PRESENTATION_SOURCE_MISMATCH"
TIMELINE_AMBIGUOUS = "TEXT_PRESENTATION_TIMELINE_AMBIGUOUS"
TEXT_CARD_AMBIGUOUS = "TEXT_OVERLAY_TEXT_CARD_AMBIGUOUS"
PROFILE_UNSUPPORTED = "TEXT_PRESENTATION_PROFILE_UNSUPPORTED"


class CaptionOverlayPlanError(ValueError):
    """Bounded C008A failure; the message is always one closed error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CaptionCueV1(BaseModel):
    """Reserved caption cue contract for a future trusted transcript source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cue_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    beat_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    order: int = Field(ge=1, le=100)
    cue_kind: Literal["caption"] = "caption"
    text: str = Field(min_length=1, max_length=2000)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_ms: int = Field(ge=0, le=600_000)
    end_ms: int = Field(gt=0, le=600_000)

    @model_validator(mode="after")
    def _consistent(self) -> CaptionCueV1:
        # ── Cue text stays canonical data; timing is always a positive window. ──
        if self.text != self.text.strip() or _sha256_text(self.text) != self.text_sha256:
            raise ValueError("caption cue text is not canonical")
        if self.end_ms <= self.start_ms:
            raise ValueError("caption cue window must be positive")
        return self


class TextOverlayCueV1(BaseModel):
    """Explicit authored on-screen text over an existing Production timeline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cue_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    beat_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    order: int = Field(ge=1, le=100)
    cue_kind: Literal["overlay"] = "overlay"
    text: str = Field(min_length=1, max_length=800)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_ms: int = Field(ge=0, le=600_000)
    end_ms: int = Field(gt=0, le=600_000)

    @model_validator(mode="after")
    def _consistent(self) -> TextOverlayCueV1:
        # ── Only outer whitespace is normalized; authored interior text is preserved. ──
        if self.text != self.text.strip() or _sha256_text(self.text) != self.text_sha256:
            raise ValueError("overlay cue text is not canonical")
        if self.end_ms <= self.start_ms:
            raise ValueError("overlay cue window must be positive")
        return self


class CaptionOverlayPlanV1(BaseModel):
    """Strict Core-authored post-production text presentation plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    production_job_id: str = Field(min_length=1, max_length=120)
    creative_package_id: str = Field(min_length=1, max_length=120)
    creative_package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    production_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_runtime_ms: int = Field(gt=0, le=600_000)
    output_profile_id: VideoOutputProfile
    caption_style_profile_id: Literal["caption.lower-third.v1"] = CAPTION_STYLE_PROFILE_ID
    overlay_style_profile_id: Literal["overlay.title-safe.v1"] = OVERLAY_STYLE_PROFILE_ID
    font_profile_id: Literal["font.windows-system-sans.v1"] = FONT_PROFILE_ID
    captions_required: bool = False
    overlays_required: bool
    captions: list[CaptionCueV1] = Field(default_factory=list, max_length=60)
    overlays: list[TextOverlayCueV1] = Field(default_factory=list, max_length=60)

    @model_validator(mode="after")
    def _consistent(self) -> CaptionOverlayPlanV1:
        # ── Authored overlays are required; captions remain policy-controlled. ──
        if self.overlays_required != bool(self.overlays):
            raise ValueError("overlays_required must match authored overlays")
        if self.captions_required and not self.captions:
            raise ValueError("required captions cannot be empty")
        _validate_cue_sequence(self.captions, self.target_runtime_ms)
        _validate_cue_sequence(self.overlays, self.target_runtime_ms)
        return self


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_digest(value: object) -> str:
    # ── Match ProductionService's stable JSON digest discipline. ────────
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def caption_overlay_plan_digest(plan: CaptionOverlayPlanV1) -> str:
    """Canonical SHA-256 over the complete validated plan."""

    return _canonical_digest(plan.model_dump(mode="json"))


def compile_caption_overlay_plan(
    *,
    production_plan: ProductionPlan,
    production_plan_digest: str,
    manifest: dict[str, object],
    creative_package_digest: str,
    caption_style_profile_id: str = CAPTION_STYLE_PROFILE_ID,
    overlay_style_profile_id: str = OVERLAY_STYLE_PROFILE_ID,
    font_profile_id: str = FONT_PROFILE_ID,
) -> CaptionOverlayPlanV1:
    """Compile explicit authored overlays against the frozen C005 Production timeline."""

    # ── Renderer authority is closed before any source text is inspected. ───
    if (
        caption_style_profile_id != CAPTION_STYLE_PROFILE_ID
        or overlay_style_profile_id != OVERLAY_STYLE_PROFILE_ID
        or font_profile_id != FONT_PROFILE_ID
    ):
        raise CaptionOverlayPlanError(PROFILE_UNSUPPORTED)

    # ── Bind the supplied durable Production digest to the exact plan object. ─
    actual_plan_digest = _canonical_digest(production_plan.model_dump(mode="json"))
    if production_plan_digest != actual_plan_digest:
        raise CaptionOverlayPlanError(SOURCE_MISMATCH)

    # ── Creative and Production identities must describe one immutable source. ─
    if (
        manifest.get("creative_package_id") != production_plan.creative_package_id
        or creative_package_digest != production_plan.creative_package_digest
    ):
        raise CaptionOverlayPlanError(SOURCE_MISMATCH)
    stage_results = manifest.get("stage_results")
    if not isinstance(stage_results, dict):
        raise CaptionOverlayPlanError(SOURCE_MISMATCH)
    try:
        script = CreativeScriptResult.model_validate(stage_results.get("script.v1"))
        shot_plan = ShotPlanResult.model_validate(stage_results.get("shot_plan.v1"))
    except ValidationError:
        # ── Pydantic errors may contain authored text, so never chain them. ───
        raise CaptionOverlayPlanError(SOURCE_MISMATCH) from None

    windows, text_card_beats = _beat_windows(production_plan, script, shot_plan)
    overlays: list[TextOverlayCueV1] = []
    for beat in script.beats:
        text = _authored_overlay_text(beat.on_screen_text)
        if text is None:
            continue
        if beat.beat_id in text_card_beats:
            raise CaptionOverlayPlanError(TEXT_CARD_AMBIGUOUS)
        window = windows.get(beat.beat_id)
        if window is None:
            raise CaptionOverlayPlanError(TIMELINE_AMBIGUOUS)
        order = len(overlays) + 1
        try:
            overlays.append(
                TextOverlayCueV1(
                    cue_id=f"overlay-{order:03d}",
                    beat_id=beat.beat_id,
                    order=order,
                    text=text,
                    text_sha256=_sha256_text(text),
                    start_ms=window[0],
                    end_ms=window[1],
                )
            )
        except ValidationError:
            raise CaptionOverlayPlanError(SOURCE_MISMATCH) from None

    try:
        return CaptionOverlayPlanV1(
            production_job_id=production_plan.production_job_id,
            creative_package_id=production_plan.creative_package_id,
            creative_package_digest=creative_package_digest,
            production_plan_digest=production_plan_digest,
            target_runtime_ms=production_plan.target_runtime_ms,
            output_profile_id=production_plan.output_profile_id,
            caption_style_profile_id=caption_style_profile_id,  # type: ignore[arg-type]
            overlay_style_profile_id=overlay_style_profile_id,  # type: ignore[arg-type]
            font_profile_id=font_profile_id,  # type: ignore[arg-type]
            captions_required=False,
            overlays_required=bool(overlays),
            captions=[],
            overlays=overlays,
        )
    except ValidationError:
        raise CaptionOverlayPlanError(SOURCE_MISMATCH) from None


def _authored_overlay_text(value: str | None) -> str | None:
    """Strip only outer whitespace; preserve authored interior whitespace exactly."""

    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _beat_windows(
    production_plan: ProductionPlan,
    script: CreativeScriptResult,
    shot_plan: ShotPlanResult,
) -> tuple[dict[str, tuple[int, int]], set[str]]:
    """Aggregate contiguous C005 task windows per beat and reject ambiguity."""

    tasks = list(production_plan.tasks)
    if [task.order for task in tasks] != list(range(1, len(tasks) + 1)):
        raise CaptionOverlayPlanError(TIMELINE_AMBIGUOUS)

    shot_to_beat = {shot.shot_id: shot.beat_id for shot in shot_plan.shots}
    task_shots = [task.shot_id for task in tasks]
    planned_shots = [shot.shot_id for shot in shot_plan.shots]
    if task_shots != planned_shots:
        raise CaptionOverlayPlanError(TIMELINE_AMBIGUOUS)

    beat_order = {beat.beat_id: beat.order for beat in script.beats}
    if set(shot_to_beat.values()) != set(beat_order):
        raise CaptionOverlayPlanError(TIMELINE_AMBIGUOUS)

    windows: dict[str, tuple[int, int]] = {}
    text_card_beats: set[str] = set()
    closed: set[str] = set()
    current: str | None = None
    last_order = 0
    cursor = 0

    for task in tasks:
        beat_id = shot_to_beat.get(task.shot_id)
        if beat_id is None or beat_id not in beat_order or task.target_duration_ms <= 0:
            raise CaptionOverlayPlanError(TIMELINE_AMBIGUOUS)
        start = cursor
        end = start + task.target_duration_ms
        if end <= start or end > 600_000:
            raise CaptionOverlayPlanError(TIMELINE_AMBIGUOUS)
        cursor = end

        if task.render_intent == "TEXT_CARD":
            text_card_beats.add(beat_id)

        if beat_id == current:
            windows[beat_id] = (windows[beat_id][0], end)
            continue
        if beat_id in closed or beat_order[beat_id] < last_order:
            raise CaptionOverlayPlanError(TIMELINE_AMBIGUOUS)
        if current is not None:
            closed.add(current)
        current = beat_id
        last_order = beat_order[beat_id]
        windows[beat_id] = (start, end)

    if cursor != production_plan.target_runtime_ms:
        raise CaptionOverlayPlanError(TIMELINE_AMBIGUOUS)
    if any(end <= start for start, end in windows.values()):
        raise CaptionOverlayPlanError(TIMELINE_AMBIGUOUS)
    return windows, text_card_beats


def _validate_cue_sequence(
    cues: list[CaptionCueV1] | list[TextOverlayCueV1],
    target_runtime_ms: int,
) -> None:
    orders = [cue.order for cue in cues]
    if orders != list(range(1, len(cues) + 1)):
        raise ValueError("cue order must be consecutive")
    previous_start = -1
    for cue in cues:
        if cue.start_ms < previous_start or cue.end_ms > target_runtime_ms:
            raise ValueError("cue timing is outside the target runtime")
        previous_start = cue.start_ms
