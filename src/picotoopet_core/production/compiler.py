"""Deterministic Creative Package → Production Plan compiler."""

from __future__ import annotations

import hashlib
from uuid import NAMESPACE_URL, uuid5

from .models import ProductionExecutionDisposition, ProductionPlan, ProductionTaskPlan
from .profile import (
    DEFAULT_FPS,
    DEFAULT_FRAME_COUNT,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    I2V_WORKFLOW_ID,
    NEGATIVE_PROMPT_POLICY_ID,
    PRODUCTION_PROFILE_ID,
    PRODUCTION_PROFILE_VERSION,
    T2V_WORKFLOW_ID,
)


def _seed(production_job_id: str, shot_id: str) -> int:
    # ── Seed is derived only from trusted plan identity ─────────────────────
    payload = f"{production_job_id}|{shot_id}|{PRODUCTION_PROFILE_VERSION}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & ((1 << 63) - 1)


def _task_id(production_job_id: str, shot_id: str) -> str:
    # ── Stable UUID avoids duplicate task creation after restart ────────────
    return str(uuid5(NAMESPACE_URL, f"picotoopet:{production_job_id}:{shot_id}"))


def _positive_prompt(shot: dict[str, object]) -> str:
    # ── Semantic order is frozen for reproducibility ────────────────────────
    continuity = ", ".join(str(item) for item in shot.get("continuity_keys", []) if str(item).strip())
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
    shot_plan = stage_results.get("shot_plan.v1")
    if not isinstance(shot_plan, dict) or not isinstance(shot_plan.get("shots"), list):
        raise ValueError("PRODUCTION_SHOT_PLAN_MISSING")

    tasks: list[ProductionTaskPlan] = []
    for expected_order, raw in enumerate(shot_plan["shots"], start=1):
        if not isinstance(raw, dict):
            raise ValueError("PRODUCTION_SHOT_INVALID")
        shot_id = str(raw.get("shot_id", "")).strip()
        order = int(raw.get("order", expected_order))
        if not shot_id or order != expected_order:
            raise ValueError("PRODUCTION_SHOT_ORDER_INVALID")
        render_intent = str(raw.get("render_intent", "")).strip()
        asset_ref = _trusted_asset_ref(manifest, shot_id)

        workflow_id: str | None = None
        disposition = ProductionExecutionDisposition.NEEDS_HUMAN
        if render_intent == "GENERATIVE_VIDEO":
            workflow_id = T2V_WORKFLOW_ID
            disposition = ProductionExecutionDisposition.EXECUTABLE
        elif render_intent == "IMAGE_TO_VIDEO" and asset_ref is not None:
            workflow_id = I2V_WORKFLOW_ID
            disposition = ProductionExecutionDisposition.EXECUTABLE

        tasks.append(
            ProductionTaskPlan(
                production_task_id=_task_id(production_job_id, shot_id),
                shot_id=shot_id,
                order=order,
                render_intent=render_intent,
                execution_disposition=disposition,
                workflow_id=workflow_id,
                positive_prompt=_positive_prompt(raw),
                negative_prompt_policy_id=NEGATIVE_PROMPT_POLICY_ID,
                seed=_seed(production_job_id, shot_id),
                width=DEFAULT_WIDTH,
                height=DEFAULT_HEIGHT,
                fps=DEFAULT_FPS,
                frame_count=DEFAULT_FRAME_COUNT,
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
        tasks=tasks,
    )
