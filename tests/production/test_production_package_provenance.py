from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from picotoopet_core.db.database import Database
from picotoopet_core.production.models import (
    ProductionPlan,
    ProductionTaskAttemptRequest,
    ProductionTaskCommitRequest,
    ProductionTaskPlan,
)
from picotoopet_core.production.repository import ProductionRepository
from picotoopet_core.production.service import ProductionService


class _CaptureStore:
    """Capture the immutable package payload without depending on filesystem ZIP bytes."""

    def __init__(self) -> None:
        self.payload: dict[str, object] | None = None

    def write_package(self, production_package_id: str, payload: dict[str, object]) -> tuple[str, str]:
        # ── Preserve the exact Core-authored payload for provenance assertions ──
        self.payload = payload
        return f"production/{production_package_id}.zip", "d" * 64


def _seed_creative_package(
    database: Database,
    *,
    creative_job_id: str,
    creative_package_id: str,
) -> dict[str, object]:
    # ── Source package mirrors the trusted Creative Package v1 provenance shape ──
    manifest: dict[str, object] = {
        "schema_version": "1.0",
        "creative_package_id": creative_package_id,
        "creative_job_id": creative_job_id,
        "project_key": "pet-dryer-us",
        "creative_profile": "creative.content_plan.v1",
        "source_result_packages": [
            {"result_package_id": "result-pkg-1", "result_digest": "1" * 64},
        ],
        "source_set_digest": "2" * 64,
        "source_findings": [
            {
                "source_finding_ref": "result-pkg-1:1",
                "finding_digest": "3" * 64,
                "evidence_ids": ["evidence-1", "evidence-2"],
            },
        ],
        "configured_model_id": "ollama:qwen3:8b",
        "stage_template_versions": {
            "idea_ranking.v1": "creative.idea-ranking.v1",
            "creative_brief.v1": "creative.brief.v1",
            "script.v1": "creative.script.v1",
            "shot_plan.v1": "creative.shot-plan.v1",
        },
        "stage_results": {
            "shot_plan.v1": {
                "schema_version": "1.0",
                "creative_profile": "creative.content_plan.v1",
                "shots": [
                    {
                        "shot_id": "shot-001",
                        "beat_id": "beat-001",
                        "order": 1,
                        "source_evidence_ids": ["evidence-1", "evidence-2"],
                        "render_intent": "GENERATIVE_VIDEO",
                    },
                ],
            },
        },
        "quality_outcome": "PASS",
        "completed_at": datetime.now(UTC).isoformat(),
    }
    timestamp = datetime.now(UTC).isoformat()
    database.execute(
        "INSERT INTO creative_jobs("
        "creative_job_id,project_key,creative_profile,creative_objective,objective_digest,source_set_digest,"
        "status,creative_package_id,idempotency_key,created_at,updated_at,finished_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            creative_job_id,
            "pet-dryer-us",
            "creative.content_plan.v1",
            None,
            "4" * 64,
            "2" * 64,
            "creative_ready",
            creative_package_id,
            f"creative:{creative_job_id}",
            timestamp,
            timestamp,
            timestamp,
        ),
    )
    database.execute(
        "INSERT INTO creative_packages("
        "creative_package_id,creative_job_id,source_set_digest,package_digest,package_relpath,manifest_json,"
        "quality_outcome,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            creative_package_id,
            creative_job_id,
            "2" * 64,
            "a" * 64,
            f"creative/{creative_package_id}.zip",
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            "PASS",
            timestamp,
        ),
    )
    return manifest


def test_production_package_freezes_full_v1_provenance(tmp_path: Path) -> None:
    # ── Use real schema/repository/service so package evidence is tested end-to-end ──
    database = Database(tmp_path / "core.db")
    database.open()
    database.apply_migrations()
    repository = ProductionRepository(database)
    store = _CaptureStore()

    creative_job_id = str(uuid4())
    creative_package_id = str(uuid4())
    source_manifest = _seed_creative_package(
        database,
        creative_job_id=creative_job_id,
        creative_package_id=creative_package_id,
    )
    job = repository.create_job(
        production_job_id=str(uuid4()),
        creative_package_id=creative_package_id,
        creative_package_digest="a" * 64,
        project_key="pet-dryer-us",
        production_profile="production.comfyui.v1",
        idempotency_key="package-provenance",
    )
    task = ProductionTaskPlan(
        production_task_id=str(uuid4()),
        shot_id="shot-001",
        order=1,
        render_intent="GENERATIVE_VIDEO",
        execution_disposition="Executable",
        workflow_id="comfy.wan22.ti2v5b.t2v.v1",
        positive_prompt="compact pet dryer; clean grooming area; slow rotating product shot",
        negative_prompt_policy_id="wan22.safe-negative.v1",
        seed=1234,
        width=832,
        height=480,
        fps=24,
        frame_count=81,
    )
    plan = ProductionPlan(
        schema_version="1.0",
        production_profile="production.comfyui.v1",
        production_job_id=job.production_job_id,
        creative_package_id=creative_package_id,
        creative_package_digest="a" * 64,
        project_key="pet-dryer-us",
        tasks=[task],
    )
    repository.save_plan(job.production_job_id, plan, "b" * 64)
    service = ProductionService(
        repository=repository,
        creative_repository=None,  # type: ignore[arg-type]  # Finalization reads the persisted Creative Package directly.
        store=store,                # type: ignore[arg-type]  # CaptureStore implements the write_package contract used here.
    )
    claim = service.claim(job.production_job_id, "pc-gpu-1")

    # ── Exercise the formal reserve → bind attempt protocol before result commit ──
    service.mark_attempt(
        job.production_job_id,
        task.production_task_id,
        ProductionTaskAttemptRequest(
            executor_id="pc-gpu-1",
            lease_token=claim.lease_token,
            comfy_prompt_id=None,
        ),
    )
    service.mark_attempt(
        job.production_job_id,
        task.production_task_id,
        ProductionTaskAttemptRequest(
            executor_id="pc-gpu-1",
            lease_token=claim.lease_token,
            comfy_prompt_id="prompt-1",
        ),
    )
    service.commit_task(
        job.production_job_id,
        task.production_task_id,
        ProductionTaskCommitRequest(
            executor_id="pc-gpu-1",
            lease_token=claim.lease_token,
            comfy_prompt_id="prompt-1",
            output_relpath="PicotooPet/production/job/001-shot-001.webm",
            output_sha256="c" * 64,
            output_bytes=4096,
            mime_type="video/webm",
            width=832,
            height=480,
            frame_count=81,
            fps=24,
        ),
    )

    payload = store.payload
    assert payload is not None

    # ── Package binds source Creative identity and active executor authority ──
    assert payload["creative_job_id"] == creative_job_id
    assert payload["executor_id"] == "pc-gpu-1"
    assert payload["comfyui_endpoint_policy"] == {
        "mode": "loopback-only",
        "base_url": "http://127.0.0.1:8188/",
    }

    # ── Trusted model identities/hashes are immutable release provenance ─────
    assert payload["models"] == [
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

    # ── Used workflow template carries a content SHA-256, not a Git blob SHA ─
    workflows = payload["workflow_templates"]
    assert isinstance(workflows, list) and len(workflows) == 1
    assert workflows[0]["workflow_id"] == "comfy.wan22.ti2v5b.t2v.v1"
    assert workflows[0]["sha256"] != "75f436cd6ba2380c19713b2dd2ea7c8a1e3a711e"
    assert len(workflows[0]["sha256"]) == 64

    # ── Per-shot evidence links creative beat/evidence, prompt identity and output ──
    outputs = payload["outputs"]
    assert isinstance(outputs, list) and len(outputs) == 1
    output = outputs[0]
    assert output["shot_id"] == "shot-001"
    assert output["beat_id"] == "beat-001"
    assert output["source_evidence_ids"] == ["evidence-1", "evidence-2"]
    assert output["seed"] == 1234
    assert len(output["prompt_digest"]) == 64
    assert output["comfy_prompt_id"] == "prompt-1"
    assert output["output_sha256"] == "c" * 64

    # ── Core inherits source provenance rather than trusting Windows to restate it ──
    creative_provenance = payload["creative_provenance"]
    assert creative_provenance["source_result_packages"] == source_manifest["source_result_packages"]
    assert creative_provenance["source_set_digest"] == source_manifest["source_set_digest"]
    assert creative_provenance["source_findings"] == source_manifest["source_findings"]
    assert creative_provenance["stage_template_versions"] == source_manifest["stage_template_versions"]
    assert creative_provenance["configured_model_id"] == source_manifest["configured_model_id"]
    assert payload["warnings"] == []
    assert payload["failures"] == []
    assert payload["quality_outcome"] == "PASS"
