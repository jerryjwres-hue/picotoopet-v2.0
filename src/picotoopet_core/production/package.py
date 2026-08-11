"""Deterministic Production Package v1 provenance builder."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime

from picotoopet_core.creative.models import CreativePackageRecord

from .models import ProductionJobRecord, ProductionPlan, ProductionTaskRecord


# ── Exact API-format workflow file content SHA-256 values shipped by 2.3.20.1 ────
TRUSTED_WORKFLOW_TEMPLATES: dict[str, dict[str, str]] = {
    "comfy.wan22.ti2v5b.t2v.v1": {
        "filename": "wan22-ti2v5b-t2v-api-v1.json",
        "sha256": "568f87baa8976030fc443c200a7c52608040f163069148442a9003f6f4409914",
    },
    "comfy.wan22.ti2v5b.i2v.v1": {
        "filename": "wan22-ti2v5b-i2v-api-v1.json",
        "sha256": "0a382cbf1f7ebb787201367273bc9269440dfe9b389bead1f4705be000452c20",
    },
}

# ── Exact pinned model identities from the trusted 2.3.20.1 model manifest ──────
TRUSTED_MODELS: list[dict[str, str]] = [
    {
        "role": "primary_video_generation",
        "filename": "wan2.2_ti2v_5B_fp16.safetensors",
        "sha256": "456f901338bd9eadbded3828b819109a9b68e8a525ca5cf8d0049a69fcfeca1e",
    },
    {
        "role": "shared_text_encoder",
        "filename": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "sha256": "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68",
    },
    {
        "role": "wan22_vae",
        "filename": "wan2.2_vae.safetensors",
        "sha256": "e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156",
    },
]


def _digest_json(value: object) -> str:
    # ── Canonical JSON digest makes prompt provenance stable across runtimes ─────
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_shots(source_manifest: dict[str, object]) -> dict[str, dict[str, object]]:
    # ── Beat/evidence provenance must come from the Core-stored Creative Package ──
    stage_results = source_manifest.get("stage_results")
    if not isinstance(stage_results, dict):
        raise ValueError("PRODUCTION_SOURCE_STAGE_RESULTS_MISSING")
    shot_plan = stage_results.get("shot_plan.v1")
    if not isinstance(shot_plan, dict):
        raise ValueError("PRODUCTION_SOURCE_SHOT_PLAN_MISSING")
    raw_shots = shot_plan.get("shots")
    if not isinstance(raw_shots, list):
        raise ValueError("PRODUCTION_SOURCE_SHOTS_MISSING")

    shots: dict[str, dict[str, object]] = {}
    for raw_shot in raw_shots:
        if not isinstance(raw_shot, dict):
            raise ValueError("PRODUCTION_SOURCE_SHOT_INVALID")
        shot_id = raw_shot.get("shot_id")
        if not isinstance(shot_id, str) or not shot_id:
            raise ValueError("PRODUCTION_SOURCE_SHOT_ID_INVALID")
        if shot_id in shots:
            raise ValueError("PRODUCTION_SOURCE_SHOT_DUPLICATE")
        shots[shot_id] = raw_shot
    return shots


def _creative_provenance(source_manifest: dict[str, object]) -> dict[str, object]:
    # ── Copy only trusted Creative/source facts required by Production Package v1 ─
    required_keys = (
        "source_result_packages",
        "source_set_digest",
        "source_findings",
        "stage_template_versions",
        "configured_model_id",
    )
    missing = [key for key in required_keys if key not in source_manifest]
    if missing:
        raise ValueError(f"PRODUCTION_SOURCE_PROVENANCE_MISSING:{','.join(missing)}")
    return {key: deepcopy(source_manifest[key]) for key in required_keys}


def build_production_package_payload(
    *,
    production_package_id: str,
    job: ProductionJobRecord,
    source_package: CreativePackageRecord,
    plan: ProductionPlan,
    tasks: list[ProductionTaskRecord],
    completed_at: datetime,
) -> dict[str, object]:
    """Build a closed PASS manifest from Core-owned immutable and durable facts."""

    # ── PASS package creation requires the active executor that produced outputs ──
    executor_id = job.lease_executor_id
    if not executor_id:
        raise ValueError("PRODUCTION_EXECUTOR_PROVENANCE_MISSING")
    if job.plan_digest is None:
        raise ValueError("PRODUCTION_PLAN_DIGEST_MISSING")
    if source_package.package_digest != job.creative_package_digest:
        raise ValueError("PRODUCTION_SOURCE_PACKAGE_DIGEST_MISMATCH")

    source_manifest = source_package.manifest
    source_shots = _source_shots(source_manifest)
    plan_tasks = {task.production_task_id: task for task in plan.tasks}

    # ── Record each used allowlisted workflow exactly once in stable order ────────
    workflow_ids = sorted({task.workflow_id for task in tasks if task.workflow_id is not None})
    workflow_templates: list[dict[str, str]] = []
    for workflow_id in workflow_ids:
        trusted = TRUSTED_WORKFLOW_TEMPLATES.get(workflow_id)
        if trusted is None:
            raise ValueError(f"PRODUCTION_WORKFLOW_PROVENANCE_UNKNOWN:{workflow_id}")
        workflow_templates.append(
            {
                "workflow_id": workflow_id,
                "filename": trusted["filename"],
                "sha256": trusted["sha256"],
            }
        )

    outputs: list[dict[str, object]] = []
    for task in sorted(tasks, key=lambda item: item.order):
        # ── Every durable output must resolve back to immutable plan + creative shot ──
        planned = plan_tasks.get(task.production_task_id)
        source_shot = source_shots.get(task.shot_id)
        if planned is None or source_shot is None:
            raise ValueError("PRODUCTION_OUTPUT_PROVENANCE_MISSING")
        beat_id = source_shot.get("beat_id")
        evidence_ids = source_shot.get("source_evidence_ids")
        if not isinstance(beat_id, str) or not isinstance(evidence_ids, list):
            raise ValueError("PRODUCTION_SHOT_EVIDENCE_INVALID")

        prompt_digest = _digest_json(
            {
                "positive_prompt": planned.positive_prompt,
                "negative_prompt_policy_id": planned.negative_prompt_policy_id,
            }
        )
        outputs.append(
            {
                "production_task_id": task.production_task_id,
                "shot_id": task.shot_id,
                "beat_id": beat_id,
                "source_evidence_ids": deepcopy(evidence_ids),
                "render_intent": planned.render_intent,
                "workflow_id": task.workflow_id,
                "prompt_digest": prompt_digest,
                "seed": planned.seed,
                "comfy_prompt_id": task.comfy_prompt_id,
                "output_relpath": task.output_relpath,
                "output_sha256": task.output_sha256,
                "output_bytes": task.output_bytes,
                "mime_type": task.output_mime_type,
                "width": task.output_width,
                "height": task.output_height,
                "frame_count": task.output_frame_count,
                "fps": task.output_fps,
            }
        )

    # ── Windows contributes execution evidence only; source provenance stays Core-owned ──
    return {
        "schema_version": "1.0",
        "production_package_id": production_package_id,
        "production_job_id": job.production_job_id,
        "production_profile": job.production_profile.value,
        "creative_package_id": source_package.creative_package_id,
        "creative_package_digest": source_package.package_digest,
        "creative_job_id": source_package.creative_job_id,
        "plan_digest": job.plan_digest,
        "executor_id": executor_id,
        "comfyui_endpoint_policy": {
            "mode": "loopback-only",
            "base_url": "http://127.0.0.1:8188/",
        },
        "workflow_templates": workflow_templates,
        "models": deepcopy(TRUSTED_MODELS),
        "outputs": outputs,
        "creative_provenance": _creative_provenance(source_manifest),
        "warnings": [],
        "failures": [],
        "completed_at": completed_at.isoformat(),
        "quality_outcome": "PASS",
    }
