from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from picotoopet_core.creative.models import CreativePackageRecord
from picotoopet_core.production.models import (
    ProductionJobRecord,
    ProductionPlan,
    ProductionTaskPlan,
    ProductionTaskRecord,
    ProductionTrustedAssetSnapshotV1,
)
from picotoopet_core.production.package import build_production_package_payload


def _plan_task(*, order: int, local_media: bool) -> ProductionTaskPlan:
    text = "Save time with gentle airflow."
    return ProductionTaskPlan.model_validate(
        {
            "production_task_id": str(uuid4()),
            "shot_id": f"shot-{order:03d}",
            "order": order,
            "render_intent": "TEXT_CARD" if local_media else "GENERATIVE_VIDEO",
            "execution_disposition": "Executable",
            "execution_backend": "local_media" if local_media else "comfy",
            "execution_profile_id": (
                "production.local.text-card.v1" if local_media else "comfy.wan22.ti2v5b.t2v.v1"
            ),
            "workflow_id": None if local_media else "comfy.wan22.ti2v5b.t2v.v1",
            "local_media": (
                {
                    "text_digest": (
                        "f65fb5a5c36901382688e08b4211c85d7bec28acd61049fef5e2e2e24c1eec1f"
                    ),
                    "text_content": text,
                    "text_profile_id": "production.local.text-card.v1",
                }
                if local_media
                else None
            ),
            "positive_prompt": "trusted production prompt",
            "negative_prompt_policy_id": "wan22.safe-negative.v1",
            "seed": order,
            "width": 832,
            "height": 480,
            "fps": 24,
            "frame_count": 73,
            "target_duration_ms": 3000,
            "trusted_input_asset_ref": None,
        }
    )


def _completed_task(job_id: str, plan: ProductionTaskPlan) -> ProductionTaskRecord:
    now = datetime.now(UTC)
    return ProductionTaskRecord(
        production_task_id=plan.production_task_id,
        production_job_id=job_id,
        shot_id=plan.shot_id,
        order=plan.order,
        render_intent=plan.render_intent,
        execution_disposition=plan.execution_disposition,
        workflow_id=plan.workflow_id,
        task_plan=plan,
        status="Succeeded",
        attempt_count=1,
        comfy_prompt_id="prompt-1" if plan.execution_backend == "comfy" else None,
        output_relpath=f"PicotooPet/production/job/{plan.order:03d}.webm",
        output_sha256=str(plan.order) * 64,
        output_bytes=4096,
        output_mime_type="video/webm",
        output_width=plan.width,
        output_height=plan.height,
        output_frame_count=plan.frame_count,
        output_fps=plan.fps,
        created_at=now,
        updated_at=now,
        finished_at=now,
    )


def _existing_asset_task(*, order: int) -> ProductionTaskPlan:
    sha256 = "e" * 64
    return ProductionTaskPlan(
        production_task_id=str(uuid4()),
        shot_id=f"shot-{order:03d}",
        order=order,
        render_intent="EXISTING_ASSET",
        execution_disposition="Executable",
        execution_backend="local_media",
        execution_profile_id="production.local.existing-image.v1",
        workflow_id=None,
        local_media=None,
        trusted_asset=ProductionTrustedAssetSnapshotV1(
            asset_id=str(uuid4()),
            scope_kind="autonomous_goal",
            scope_id="goal-001",
            managed_root_id="windows.comfy-input.v1",
            managed_relpath=f"PicotooPet/assets/v1/ee/{sha256}.png",
            sha256=sha256,
            size_bytes=2048,
            media_type="image/png",
            width=1200,
            height=800,
        ),
        positive_prompt="trusted existing asset",
        negative_prompt_policy_id="wan22.safe-negative.v1",
        seed=order,
        width=832,
        height=480,
        fps=24,
        frame_count=73,
        target_duration_ms=3000,
        trusted_input_asset_ref=None,
    )


def test_mixed_comfy_and_text_card_share_one_package_without_raw_text() -> None:
    now = datetime.now(UTC)
    job_id = str(uuid4())
    creative_job_id = str(uuid4())
    creative_package_id = str(uuid4())
    comfy = _plan_task(order=1, local_media=False)
    text_card = _plan_task(order=2, local_media=True)
    existing_asset = _existing_asset_task(order=3)
    plan = ProductionPlan(
        schema_version="1.0",
        production_profile="production.comfyui.v1",
        production_job_id=job_id,
        creative_package_id=creative_package_id,
        creative_package_digest="a" * 64,
        project_key="pet-dryer-us",
        output_profile_id="video.landscape.v1",
        target_runtime_ms=9000,
        tasks=[comfy, text_card, existing_asset],
    )
    job = ProductionJobRecord(
        production_job_id=job_id,
        creative_package_id=creative_package_id,
        creative_package_digest="a" * 64,
        project_key="pet-dryer-us",
        production_profile="production.comfyui.v1",
        plan_digest="b" * 64,
        status="QualityCheck",
        lease_executor_id="pc-gpu-1",
        idempotency_key="mixed-package",
        created_at=now,
        updated_at=now,
    )
    source = CreativePackageRecord(
        creative_package_id=creative_package_id,
        creative_job_id=creative_job_id,
        source_set_digest="2" * 64,
        package_digest="a" * 64,
        package_relpath="creative/source.zip",
        manifest={
            "source_result_packages": [],
            "source_set_digest": "2" * 64,
            "source_findings": [],
            "stage_template_versions": {},
            "configured_model_id": "ollama:qwen3:8b",
            "stage_results": {
                "shot_plan.v1": {
                    "shots": [
                        {
                            "shot_id": comfy.shot_id,
                            "beat_id": "beat-001",
                            "source_evidence_ids": [],
                        },
                        {
                            "shot_id": text_card.shot_id,
                            "beat_id": "beat-002",
                            "source_evidence_ids": [],
                        },
                        {
                            "shot_id": existing_asset.shot_id,
                            "beat_id": "beat-003",
                            "source_evidence_ids": [],
                        },
                    ]
                }
            },
        },
        quality_outcome="PASS",
        created_at=now,
    )

    payload = build_production_package_payload(
        production_package_id=str(uuid4()),
        job=job,
        source_package=source,
        plan=plan,
        tasks=[
            _completed_task(job_id, comfy),
            _completed_task(job_id, text_card),
            _completed_task(job_id, existing_asset),
        ],
        completed_at=now,
    )

    assert [item["workflow_id"] for item in payload["workflow_templates"]] == [
        "comfy.wan22.ti2v5b.t2v.v1"
    ]
    assert payload["models"]
    outputs = payload["outputs"]
    assert outputs[0]["execution_backend"] == "comfy"
    assert outputs[0]["execution_profile_id"] == "comfy.wan22.ti2v5b.t2v.v1"
    assert outputs[0]["text_digest"] is None
    assert outputs[1]["execution_backend"] == "local_media"
    assert outputs[1]["execution_profile_id"] == "production.local.text-card.v1"
    assert outputs[1]["text_digest"] == text_card.local_media.text_digest
    assert "text_content" not in outputs[1]
    assert outputs[2]["execution_profile_id"] == "production.local.existing-image.v1"
    assert outputs[2]["workflow_id"] is None
    assert outputs[2]["source_asset"] == {
        "asset_id": existing_asset.trusted_asset.asset_id,
        "sha256": "e" * 64,
        "media_type": "image/png",
        "width": 1200,
        "height": 800,
        "managed_root_id": "windows.comfy-input.v1",
        "managed_relpath": f"PicotooPet/assets/v1/ee/{'e' * 64}.png",
    }
    assert not any("source_path" in key or "absolute" in key for key in outputs[2])


def test_text_card_only_package_does_not_claim_comfy_models() -> None:
    now = datetime.now(UTC)
    job_id = str(uuid4())
    creative_job_id = str(uuid4())
    creative_package_id = str(uuid4())
    text_card = _plan_task(order=1, local_media=True)
    plan = ProductionPlan(
        schema_version="1.0",
        production_profile="production.comfyui.v1",
        production_job_id=job_id,
        creative_package_id=creative_package_id,
        creative_package_digest="a" * 64,
        project_key="pet-dryer-us",
        output_profile_id="video.landscape.v1",
        target_runtime_ms=3000,
        tasks=[text_card],
    )
    job = ProductionJobRecord(
        production_job_id=job_id,
        creative_package_id=creative_package_id,
        creative_package_digest="a" * 64,
        project_key="pet-dryer-us",
        production_profile="production.comfyui.v1",
        plan_digest="b" * 64,
        status="QualityCheck",
        lease_executor_id="pc-gpu-1",
        idempotency_key="text-card-only-package",
        created_at=now,
        updated_at=now,
    )
    source = CreativePackageRecord(
        creative_package_id=creative_package_id,
        creative_job_id=creative_job_id,
        source_set_digest="2" * 64,
        package_digest="a" * 64,
        package_relpath="creative/source.zip",
        manifest={
            "source_result_packages": [],
            "source_set_digest": "2" * 64,
            "source_findings": [],
            "stage_template_versions": {},
            "configured_model_id": "ollama:qwen3:8b",
            "stage_results": {
                "shot_plan.v1": {
                    "shots": [
                        {
                            "shot_id": text_card.shot_id,
                            "beat_id": "beat-001",
                            "source_evidence_ids": [],
                        }
                    ]
                }
            },
        },
        quality_outcome="PASS",
        created_at=now,
    )

    payload = build_production_package_payload(
        production_package_id=str(uuid4()),
        job=job,
        source_package=source,
        plan=plan,
        tasks=[_completed_task(job_id, text_card)],
        completed_at=now,
    )

    assert payload["workflow_templates"] == []
    assert payload["models"] == []
