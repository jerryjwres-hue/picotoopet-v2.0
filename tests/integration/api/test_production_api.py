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


def _seed_creative_package(database) -> str:  # type: ignore[no-untyped-def]
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
        "quality_outcome": "PASS",
        "stage_results": {
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
                        "text_reference": None,
                        "production_notes": "renderer-neutral",
                        "render_intent": "GENERATIVE_VIDEO",
                    }
                ],
                "warnings": [],
                "needs_deep_ai": False,
                "needs_human": False,
            }
        },
    }
    database.execute(
        "INSERT INTO creative_jobs(creative_job_id,project_key,creative_profile,creative_objective,objective_digest,"
        "source_set_digest,status,creative_package_id,idempotency_key,created_at,updated_at,finished_at) "
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
        "INSERT INTO creative_packages(creative_package_id,creative_job_id,source_set_digest,package_digest,"
        "package_relpath,manifest_json,quality_outcome,created_at) VALUES (?,?,?,?,?,?,?,?)",
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
