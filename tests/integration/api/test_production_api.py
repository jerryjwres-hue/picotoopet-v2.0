from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def _app(tmp_path: Path):  # type: ignore[no-untyped-def]
    # ── Authenticated Core fixture ───────────────────────────────────────────
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(paths=RuntimePaths.from_root(tmp_path / "runtime"), api_token=token)
    app = create_app(settings)
    return app, {"Authorization": f"Bearer {token}"}


def _seed_creative_package(  # type: ignore[no-untyped-def]
    database,
    *,
    render_intent: str = "GENERATIVE_VIDEO",
    text_reference: str | None = None,
) -> str:
    # ── Minimal persisted creative_ready package ─────────────────────────────
    now = datetime.now(UTC).isoformat()
    creative_job_id = str(uuid4())
    creative_package_id = str(uuid4())
    manifest = {
        "schema_version": "1.0",
        "creative_package_id": creative_package_id,
        "creative_job_id": creative_job_id,
        "project_key": "pet-dryer-us",
        "creative_profile": "creative.content_plan.v1",
        "source_set_digest": "a" * 64,
        "source_result_packages": [],
        "source_findings": [],
        "configured_model_id": "ollama:qwen3:8b",
        "stage_template_versions": {},
        "quality_outcome": "PASS",
        "stage_results": {
            "creative_brief.v1": {
                "schema_version": "1.0",
                "creative_profile": "creative.content_plan.v1",
                "selected_idea_id": "idea-001",
                "target_audience": "pet owners",
                "customer_problem": "slow drying",
                "value_proposition": "save time",
                "primary_hook": "Dry faster",
                "emotional_tone": "practical",
                "content_format": "short video",
                "duration_min_seconds": 3,
                "duration_max_seconds": 10,
                "message_hierarchy": ["problem", "solution"],
                "required_source_finding_refs": ["result:finding:1"],
                "required_source_evidence_ids": ["reviews:key:r1"],
                "prohibited_claims": [],
                "cta_intent": "learn more",
                "continuity_notes": [],
                "needs_deep_ai": False,
                "needs_human": False,
            },
            "script.v1": {
                "schema_version": "1.0",
                "creative_profile": "creative.content_plan.v1",
                "script_id": "script-001",
                "title": "Dry faster",
                "target_duration_seconds": 3,
                "beats": [
                    {
                        "beat_id": "beat-001",
                        "order": 1,
                        "duration_seconds": 3,
                        "voiceover": "Drying time matters.",
                        "on_screen_text": None,
                        "visual_intent": "Compact dryer in use",
                        "claim_source_evidence_ids": [],
                        "unsupported_claim": False,
                    }
                ],
                "cta_beat_id": "beat-001",
                "warnings": [],
                "needs_deep_ai": False,
                "needs_human": False,
            },
            "shot_plan.v1": {
                "schema_version": "1.0",
                "creative_profile": "creative.content_plan.v1",
                "shots": [
                    {
                        "shot_id": "shot-001",
                        "beat_id": "beat-001",
                        "order": 1,
                        "duration_seconds": 3.0,
                        "subject": "compact pet dryer",
                        "environment": "clean grooming area",
                        "action": "product rotates",
                        "framing": "medium product shot",
                        "lighting_style": "soft daylight",
                        "continuity_keys": [],
                        "required_facts": [],
                        "source_evidence_ids": [],
                        "text_reference": text_reference,
                        "production_notes": "renderer-neutral",
                        "render_intent": render_intent,
                    }
                ],
                "warnings": [],
                "needs_deep_ai": False,
                "needs_human": False,
            }
        },
    }
    database.execute(
        "INSERT INTO creative_jobs("
        "creative_job_id,project_key,creative_profile,creative_objective,objective_digest,"
        "source_set_digest,status,creative_package_id,idempotency_key,"
        "created_at,updated_at,finished_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            creative_job_id,
            "pet-dryer-us",
            "creative.content_plan.v1",
            None,
            "b" * 64,
            "a" * 64,
            "creative_ready",
            creative_package_id,
            f"creative-{creative_job_id}",
            now,
            now,
            now,
        ),
    )
    database.execute(
        "INSERT INTO creative_packages("
        "creative_package_id,creative_job_id,source_set_digest,package_digest,"
        "package_relpath,manifest_json,quality_outcome,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            creative_package_id,
            creative_job_id,
            "a" * 64,
            "c" * 64,
            f"runtime/creative/packages/{creative_package_id}.zip",
            json.dumps(manifest),
            "PASS",
            now,
        ),
    )
    return creative_package_id


def test_create_production_job_accepts_only_closed_profile_fields(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        package_id = _seed_creative_package(app.state.services.database)
        payload = {
            "creative_package_id": package_id,
            "production_profile": "production.comfyui.v1",
            "idempotency_key": "production-api-demo",
        }
        response = client.post("/api/v1/production/jobs", headers=headers, json=payload)
        assert response.status_code == 200
        assert response.json()["production_profile"] == "production.comfyui.v1"

        injected = {
            **payload,
            "endpoint": "https://example.com",
            "workflow_json": {"1": {"class_type": "Anything"}},
            "model_path": "C:/models/remote.safetensors",
            "command": "powershell.exe",
        }
        rejected = client.post("/api/v1/production/jobs", headers=headers, json=injected)
        assert rejected.status_code == 422


def test_only_creative_ready_pass_packages_are_eligible(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        package_id = _seed_creative_package(app.state.services.database)
        response = client.get("/api/v1/production/eligible", headers=headers)
        assert response.status_code == 200
        ids = {item["creative_package_id"] for item in response.json()}
        assert package_id in ids


def test_production_routes_require_auth(tmp_path: Path) -> None:
    app, _headers = _app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/v1/production/jobs").status_code == 401


def test_idempotent_replay_reuses_bound_plan_after_compiler_upgrade(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        package_id = _seed_creative_package(app.state.services.database)
        payload = {
            "creative_package_id": package_id,
            "production_profile": "production.comfyui.v1",
            "idempotency_key": "production-upgrade-replay",
        }
        first = client.post("/api/v1/production/jobs", headers=headers, json=payload)
        assert first.status_code == 200
        job_id = first.json()["production_job_id"]

        # Simulate an immutable pre-C005 plan already bound to this job.
        row = app.state.services.database.fetchone(
            "SELECT plan_json FROM production_jobs WHERE production_job_id=?",
            (job_id,),
        )
        plan = json.loads(row["plan_json"])
        plan.pop("output_profile_id", None)
        plan.pop("target_runtime_ms", None)
        for task in plan["tasks"]:
            task.pop("target_duration_ms", None)
            task["frame_count"] = 81
        legacy_json = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        legacy_digest = "d" * 64
        app.state.services.database.execute(
            "UPDATE production_jobs SET plan_json=?,plan_digest=? WHERE production_job_id=?",
            (legacy_json, legacy_digest, job_id),
        )

        replay = client.post("/api/v1/production/jobs", headers=headers, json=payload)
        assert replay.status_code == 200
        assert replay.json()["production_job_id"] == job_id
        assert replay.json()["plan_digest"] == legacy_digest

        preserved = app.state.services.database.fetchone(
            "SELECT plan_json,plan_digest FROM production_jobs WHERE production_job_id=?",
            (job_id,),
        )
        assert preserved["plan_json"] == legacy_json
        assert preserved["plan_digest"] == legacy_digest


def test_text_card_uses_existing_attempt_commit_and_package_routes(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        package_id = _seed_creative_package(
            app.state.services.database,
            render_intent="TEXT_CARD",
            text_reference="Save time with gentle airflow.",
        )
        created = client.post(
            "/api/v1/production/jobs",
            headers=headers,
            json={
                "creative_package_id": package_id,
                "production_profile": "production.comfyui.v1",
                "idempotency_key": "production-text-card",
            },
        )
        assert created.status_code == 200
        job_id = created.json()["production_job_id"]
        plan = client.get(f"/api/v1/production/jobs/{job_id}/plan", headers=headers).json()
        task = plan["tasks"][0]
        assert task["execution_backend"] == "local_media"
        assert task["workflow_id"] is None

        claim = client.post(
            f"/api/v1/production/jobs/{job_id}/claim",
            headers=headers,
            json={"executor_id": "pc-gpu-1"},
        ).json()
        task_id = task["production_task_id"]
        attempt = client.post(
            f"/api/v1/production/jobs/{job_id}/tasks/{task_id}/attempt",
            headers=headers,
            json={
                "executor_id": "pc-gpu-1",
                "lease_token": claim["lease_token"],
                "comfy_prompt_id": None,
            },
        )
        assert attempt.status_code == 200
        committed = client.post(
            f"/api/v1/production/jobs/{job_id}/tasks/{task_id}/result",
            headers=headers,
            json={
                "executor_id": "pc-gpu-1",
                "lease_token": claim["lease_token"],
                "comfy_prompt_id": None,
                "output_relpath": "PicotooPet/production/job/001-text-card.webm",
                "output_sha256": "d" * 64,
                "output_bytes": 4096,
                "mime_type": "video/webm",
                "width": task["width"],
                "height": task["height"],
                "frame_count": task["frame_count"],
                "fps": task["fps"],
            },
        )
        assert committed.status_code == 200
        assert committed.json()["comfy_prompt_id"] is None
        packaged = client.get(
            f"/api/v1/production/jobs/{job_id}/package",
            headers=headers,
        )
        assert packaged.status_code == 200
        output = packaged.json()["manifest"]["outputs"][0]
        assert output["execution_backend"] == "local_media"
        assert output["text_digest"] == task["local_media"]["text_digest"]
        assert "text_content" not in output
