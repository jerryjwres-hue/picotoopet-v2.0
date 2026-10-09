"""Deterministic Creative Package → Production Plan compiler."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from picotoopet_core.creative.models import (
    CreativeBriefResult,
    CreativeScriptResult,
    ShotPlanResult,
)

from .models import (
    ProductionExecutionDisposition,
    ProductionExecutionProfile,
    ProductionPlan,
    ProductionTaskPlan,
    ProductionTrustedAssetSnapshotV1,
)
from .profile import (
    I2V_WORKFLOW_ID,
    MAX_FRAME_COUNT,
    NEGATIVE_PROMPT_POLICY_ID,
    PRODUCTION_PROFILE_ID,
    PRODUCTION_PROFILE_VERSION,
    T2V_WORKFLOW_ID,
    TIMELINE_TOLERANCE_SECONDS,
    VIDEO_OUTPUT_PROFILES,
    duration_ms,
    frame_count_for_duration,
)


def _seed(production_job_id: str, shot_id: str) -> int:
    # ── Seed is derived only from trusted plan identity ─────────────────────
    payload = f"{production_job_id}|{shot_id}|{PRODUCTION_PROFILE_VERSION}".encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & ((1 << 63) - 1)


def _task_id(production_job_id: str, shot_id: str) -> str:
    # ── Stable UUID avoids duplicate task creation after restart ────────────
    return str(uuid5(NAMESPACE_URL, f"picotoopet:{production_job_id}:{shot_id}"))


def _positive_prompt(shot: dict[str, object]) -> str:
    # ── Semantic order is frozen for reproducibility ────────────────────────
    continuity = ", ".join(
        str(item) for item in shot.get("continuity_keys", []) if str(item).strip()
    )
    facts = ", ".join(str(item) for item in shot.get("required_facts", []) if str(item).strip())
    segments = [
        str(shot.get("subject", "")).strip(),
        str(shot.get("environment", "")).strip(),
        str(shot.get("action", "")).strip(),
        str(shot.get("framing", "")).strip(),
        str(shot.get("lighting_style", "")).strip(),
        continuity,
        facts,
    ]
    return "; ".join(segment for segment in segments if segment)


def _trusted_asset_ref(manifest: dict[str, object], shot_id: str) -> str | None:
    # ── Only Core-authored Creative Package metadata may provide an asset ref ─
    assets = manifest.get("trusted_local_assets")
    if not isinstance(assets, dict):
        return None
    value = assets.get(shot_id)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:300]


def compile_production_plan(
    production_job_id: str,
    manifest: dict[str, object],
    creative_package_digest: str,
    *,
    trusted_assets: Mapping[str, ProductionTrustedAssetSnapshotV1] | None = None,
) -> ProductionPlan:
    """Compile a renderer-neutral 19.1 package into a closed 20.1 plan."""

    if manifest.get("quality_outcome") != "PASS":
        raise ValueError("PRODUCTION_CREATIVE_PACKAGE_NOT_PASS")
    creative_package_id = manifest.get("creative_package_id")
    project_key = manifest.get("project_key")
    stage_results = manifest.get("stage_results")
    if not isinstance(creative_package_id, str) or not isinstance(project_key, str):
        raise ValueError("PRODUCTION_CREATIVE_PACKAGE_IDENTITY_INVALID")
    if not isinstance(stage_results, dict):
        raise ValueError("PRODUCTION_SHOT_PLAN_MISSING")
    try:
        brief = CreativeBriefResult.model_validate(stage_results.get("creative_brief.v1"))
    except ValidationError as error:
        raise ValueError("PRODUCTION_CREATIVE_BRIEF_INVALID") from error
    try:
        script = CreativeScriptResult.model_validate(stage_results.get("script.v1"))
    except ValidationError as error:
        raise ValueError("PRODUCTION_SCRIPT_INVALID") from error
    try:
        shot_plan = ShotPlanResult.model_validate(stage_results.get("shot_plan.v1"))
    except ValidationError as error:
        raise ValueError("PRODUCTION_SHOT_PLAN_INVALID") from error

    script_beats = {item.beat_id for item in script.beats}
    shot_beats = {item.beat_id for item in shot_plan.shots}
    if shot_beats != script_beats:
        raise ValueError("PRODUCTION_TIMELINE_BEAT_MISMATCH")
    shot_duration = sum(item.duration_seconds for item in shot_plan.shots)
    if abs(shot_duration - script.target_duration_seconds) > TIMELINE_TOLERANCE_SECONDS:
        raise ValueError("PRODUCTION_TIMELINE_MISMATCH")

    output_profile = VIDEO_OUTPUT_PROFILES[brief.output_profile_id]
    script_beats_by_id = {item.beat_id: item for item in script.beats}

    tasks: list[ProductionTaskPlan] = []
    for expected_order, shot in enumerate(shot_plan.shots, start=1):
        raw = shot.model_dump(mode="json")
        shot_id = shot.shot_id
        order = shot.order
        if not shot_id or order != expected_order:
            raise ValueError("PRODUCTION_SHOT_ORDER_INVALID")
        render_intent = shot.render_intent.value
        asset_ref = _trusted_asset_ref(manifest, shot_id)
        target_duration = duration_ms(shot.duration_seconds)
        duration_supported = True
        try:
            frame_count = frame_count_for_duration(shot.duration_seconds, output_profile.fps)
        except ValueError:
            duration_supported = False
            frame_count = MAX_FRAME_COUNT

        workflow_id: str | None = None
        execution_backend: str | None = None
        execution_profile_id: str | None = None
        local_media: dict[str, str] | None = None
        trusted_asset: ProductionTrustedAssetSnapshotV1 | None = None
        disposition = ProductionExecutionDisposition.NEEDS_HUMAN
        if duration_supported and render_intent == "GENERATIVE_VIDEO":
            workflow_id = T2V_WORKFLOW_ID
            execution_backend = "comfy"
            execution_profile_id = T2V_WORKFLOW_ID
            disposition = ProductionExecutionDisposition.EXECUTABLE
        elif duration_supported and render_intent == "IMAGE_TO_VIDEO" and asset_ref is not None:
            workflow_id = I2V_WORKFLOW_ID
            execution_backend = "comfy"
            execution_profile_id = I2V_WORKFLOW_ID
            disposition = ProductionExecutionDisposition.EXECUTABLE
        elif duration_supported and render_intent == "TEXT_CARD":
            script_beat = script_beats_by_id[shot.beat_id]
            text = shot.text_reference
            if text is None or not text.strip():
                text = script_beat.on_screen_text
            if text is not None and text.strip():
                text = text.strip()
                execution_backend = "local_media"
                execution_profile_id = ProductionExecutionProfile.TEXT_CARD_V1.value
                local_media = {
                    "text_digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "text_content": text,
                    "text_profile_id": ProductionExecutionProfile.TEXT_CARD_V1.value,
                }
                disposition = ProductionExecutionDisposition.EXECUTABLE
        elif duration_supported and render_intent == "EXISTING_ASSET":
            existing_asset_ref = shot.existing_asset_ref
            if existing_asset_ref is None:
                raise ValueError("PRODUCTION_TRUSTED_ASSET_NOT_FOUND")
            trusted_asset = (trusted_assets or {}).get(existing_asset_ref)
            if trusted_asset is None or trusted_asset.asset_id != existing_asset_ref:
                raise ValueError("PRODUCTION_TRUSTED_ASSET_NOT_FOUND")
            goal_prefix = "autonomous-goal:"
            if (
                not project_key.startswith(goal_prefix)
                or trusted_asset.scope_kind != "autonomous_goal"
                or trusted_asset.scope_id != project_key[len(goal_prefix) :]
            ):
                raise ValueError("PRODUCTION_TRUSTED_ASSET_SCOPE_INVALID")
            execution_backend = "local_media"
            execution_profile_id = ProductionExecutionProfile.EXISTING_IMAGE_V1.value
            disposition = ProductionExecutionDisposition.EXECUTABLE

        tasks.append(
            ProductionTaskPlan(
                production_task_id=_task_id(production_job_id, shot_id),
                shot_id=shot_id,
                order=order,
                render_intent=render_intent,
                execution_disposition=disposition,
                execution_backend=execution_backend,
                execution_profile_id=execution_profile_id,
                workflow_id=workflow_id,
                local_media=local_media,
                trusted_asset=trusted_asset,
                positive_prompt=_positive_prompt(raw),
                negative_prompt_policy_id=NEGATIVE_PROMPT_POLICY_ID,
                seed=_seed(production_job_id, shot_id),
                width=output_profile.width,
                height=output_profile.height,
                fps=output_profile.fps,
                frame_count=frame_count,
                target_duration_ms=target_duration,
                trusted_input_asset_ref=asset_ref,
            )
        )

    return ProductionPlan(
        schema_version="1.0",
        production_profile=PRODUCTION_PROFILE_ID,
        production_job_id=production_job_id,
        creative_package_id=creative_package_id,
        creative_package_digest=creative_package_digest,
        project_key=project_key,
        output_profile_id=brief.output_profile_id,
        target_runtime_ms=sum(item.target_duration_ms for item in tasks),
        tasks=tasks,
    )
