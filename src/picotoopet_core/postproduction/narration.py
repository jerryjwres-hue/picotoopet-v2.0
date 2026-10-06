"""C007A: deterministic NarrationPlanV1 derived from CreativePackage + frozen ProductionPlan.

Narration is downstream audio planning, not a Production task. This module is read-only:
it persists nothing and never mutates the Production lifecycle.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from picotoopet_core.creative.models import CreativeScriptResult, ShotPlanResult
from picotoopet_core.production.models import ProductionPlan
from picotoopet_core.production.service import ProductionService

TTS_PROFILE_ID = "narration.local.windows.v1"
VOICE_PROFILE_ID = "voice.windows.default.v1"

NOT_READY = "NARRATION_PLAN_NOT_READY"
TIMELINE_AMBIGUOUS = "NARRATION_TIMELINE_AMBIGUOUS"
SOURCE_MISMATCH = "NARRATION_SOURCE_MISMATCH"
PROFILE_UNSUPPORTED = "NARRATION_PROFILE_UNSUPPORTED"


class NarrationPlanError(ValueError):
    """Bounded narration failure; the message is always one of the closed codes."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class NarrationSegmentPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    segment_id: str = Field(min_length=1, max_length=80)
    beat_id: str = Field(min_length=1, max_length=80)
    order: int = Field(ge=1, le=100)
    text: str = Field(min_length=1, max_length=2000)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def _consistent(self) -> NarrationSegmentPlan:
        if self.end_ms <= self.start_ms:
            raise ValueError("segment window must be positive")
        if _sha256(self.text) != self.text_sha256:
            raise ValueError("segment text digest mismatch")
        return self


class NarrationPlanV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    production_job_id: str = Field(min_length=1, max_length=80)
    creative_package_id: str = Field(min_length=1, max_length=80)
    creative_package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    production_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_runtime_ms: int = Field(gt=0, le=600_000)
    tts_profile_id: Literal["narration.local.windows.v1"]
    voice_profile_id: Literal["voice.windows.default.v1"]
    narration_required: bool
    segments: list[NarrationSegmentPlan] = Field(max_length=60)

    @model_validator(mode="after")
    def _consistent(self) -> NarrationPlanV1:
        if self.narration_required != bool(self.segments):
            raise ValueError("narration_required must match segments")
        previous_end = 0
        for index, segment in enumerate(self.segments, start=1):
            if segment.order != index or segment.start_ms < previous_end:
                raise ValueError("segments must be ordered and non-overlapping")
            previous_end = segment.end_ms
        if previous_end > self.target_runtime_ms:
            raise ValueError("segments exceed target runtime")
        return self


class NarrationPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan: NarrationPlanV1
    narration_plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def narration_plan_digest(plan: NarrationPlanV1) -> str:
    """Canonical digest over the complete bounded plan."""

    encoded = json.dumps(
        plan.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256(encoded)


def compile_narration_plan(
    *,
    production_plan: ProductionPlan,
    production_plan_digest: str,
    manifest: dict[str, object],
    creative_package_digest: str,
    tts_profile_id: str = TTS_PROFILE_ID,
    voice_profile_id: str = VOICE_PROFILE_ID,
) -> NarrationPlanV1:
    """Derive the narration plan; ProductionPlan task durations are the timing authority."""

    if tts_profile_id != TTS_PROFILE_ID or voice_profile_id != VOICE_PROFILE_ID:
        raise NarrationPlanError(PROFILE_UNSUPPORTED)

    # ── Identity: Creative and Production sources must describe the same package ──
    if (
        manifest.get("creative_package_id") != production_plan.creative_package_id
        or creative_package_digest != production_plan.creative_package_digest
    ):
        raise NarrationPlanError(SOURCE_MISMATCH)
    stage_results = manifest.get("stage_results")
    if not isinstance(stage_results, dict):
        raise NarrationPlanError(SOURCE_MISMATCH)
    try:
        script = CreativeScriptResult.model_validate(stage_results.get("script.v1"))
        shot_plan = ShotPlanResult.model_validate(stage_results.get("shot_plan.v1"))
    except ValidationError:
        # ── Never chain: pydantic errors embed raw input (voiceover text) ──
        raise NarrationPlanError(SOURCE_MISMATCH) from None

    voiced = {
        beat.beat_id: beat.voiceover.strip()
        for beat in script.beats
        if beat.voiceover is not None and beat.voiceover.strip()
    }
    segments: list[NarrationSegmentPlan] = []
    if voiced:
        windows = _beat_windows(production_plan, script, shot_plan)
        for beat in script.beats:
            text = voiced.get(beat.beat_id)
            if text is None:
                continue
            window = windows.get(beat.beat_id)
            if window is None:
                raise NarrationPlanError(TIMELINE_AMBIGUOUS)
            order = len(segments) + 1
            try:
                segments.append(
                    NarrationSegmentPlan(
                        segment_id=f"segment-{order:03d}",
                        beat_id=beat.beat_id,
                        order=order,
                        text=text,
                        text_sha256=_sha256(text),
                        start_ms=window[0],
                        end_ms=window[1],
                    )
                )
            except ValidationError:
                raise NarrationPlanError(TIMELINE_AMBIGUOUS) from None

    try:
        return NarrationPlanV1(
            schema_version="1.0",
            production_job_id=production_plan.production_job_id,
            creative_package_id=production_plan.creative_package_id,
            creative_package_digest=creative_package_digest,
            production_plan_digest=production_plan_digest,
            target_runtime_ms=production_plan.target_runtime_ms,
            tts_profile_id=tts_profile_id,  # type: ignore[arg-type]
            voice_profile_id=voice_profile_id,  # type: ignore[arg-type]
            narration_required=bool(segments),
            segments=segments,
        )
    except ValidationError:
        raise NarrationPlanError(TIMELINE_AMBIGUOUS) from None


def _beat_windows(
    production_plan: ProductionPlan,
    script: CreativeScriptResult,
    shot_plan: ShotPlanResult,
) -> dict[str, tuple[int, int]]:
    """Aggregate contiguous Production task windows per beat; ambiguity is rejected."""

    tasks = sorted(production_plan.tasks, key=lambda item: item.order)
    if [task.order for task in tasks] != list(range(1, len(tasks) + 1)):
        raise NarrationPlanError(TIMELINE_AMBIGUOUS)
    shot_to_beat = {shot.shot_id: shot.beat_id for shot in shot_plan.shots}
    if {task.shot_id for task in tasks} != set(shot_to_beat) or len(tasks) != len(shot_to_beat):
        raise NarrationPlanError(TIMELINE_AMBIGUOUS)
    beat_order = {beat.beat_id: beat.order for beat in script.beats}

    windows: dict[str, tuple[int, int]] = {}
    closed: set[str] = set()
    current: str | None = None
    last_order = 0
    cursor = 0
    for task in tasks:
        beat_id = shot_to_beat[task.shot_id]
        if beat_id not in beat_order:
            raise NarrationPlanError(TIMELINE_AMBIGUOUS)
        start, end = cursor, cursor + task.target_duration_ms
        cursor = end
        if beat_id == current:
            windows[beat_id] = (windows[beat_id][0], end)
            continue
        if beat_id in closed or beat_order[beat_id] < last_order:
            raise NarrationPlanError(TIMELINE_AMBIGUOUS)
        if current is not None:
            closed.add(current)
        current = beat_id
        last_order = beat_order[beat_id]
        windows[beat_id] = (start, end)
    return windows


class NarrationPlanService:
    """Read-only facade over existing Production/Creative repositories (no new table)."""

    def __init__(self, production: ProductionService) -> None:
        self._production = production

    def get_plan(self, production_job_id: str) -> NarrationPlanResponse:
        repository = self._production.repository
        job = repository.get_job(production_job_id)  # KeyError => unknown job
        if job.plan_digest is None:
            raise NarrationPlanError(NOT_READY)
        try:
            production_plan = repository.plan_for(production_job_id)
        except ValueError:
            raise NarrationPlanError(NOT_READY) from None
        try:
            package = self._production.creative_repository.get_package(job.creative_package_id)
        except KeyError:
            raise NarrationPlanError(SOURCE_MISMATCH) from None
        if (
            production_plan.production_job_id != job.production_job_id
            or package.package_digest != job.creative_package_digest
        ):
            raise NarrationPlanError(SOURCE_MISMATCH)
        plan = compile_narration_plan(
            production_plan=production_plan,
            production_plan_digest=job.plan_digest,
            manifest=package.manifest,
            creative_package_digest=package.package_digest,
        )
        return NarrationPlanResponse(plan=plan, narration_plan_digest=narration_plan_digest(plan))
