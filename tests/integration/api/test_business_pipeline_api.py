from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.business.models import WorkPackageManifest
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def _app(tmp_path: Path):  # type: ignore[no-untyped-def]
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(paths=RuntimePaths.from_root(tmp_path / "runtime"), api_token=token)
    app = create_app(settings)
    return app, {"Authorization": f"Bearer {token}"}


def _seed_work_package(app) -> str:  # type: ignore[no-untyped-def]
    package_id = str(uuid4())
    manifest = WorkPackageManifest.model_validate(
        {
            "schema_version": "1.0",
            "package_id": package_id,
            "idempotency_key": f"work:{package_id}",
            "producer_id": "amazon-research-app",
            "producer_version": "1.0.0",
            "created_at": "2026-08-11T12:00:00Z",
            "project_key": "pet-dryer-us",
            "analysis_profile": "reviews.voice_of_customer.v1",
            "objective": "Identify supported customer problems.",
            "inputs": [
                {
                    "artifact_id": "reviews",
                    "path": "inputs/reviews.jsonl",
                    "media_type": "application/x-ndjson",
                    "sha256": "a" * 64,
                    "size_bytes": 128,
                    "record_key_field": "review_id",
                }
            ],
        }
    )
    app.state.services.business_repository.create_or_get_work_package(
        manifest,
        source_digest="b" * 64,
        compressed_size_bytes=512,
    )
    return package_id


def test_pipeline_api_creates_lists_gets_and_reconciles_run(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        work_package_id = _seed_work_package(app)
        payload = {
            "work_package_id": work_package_id,
            "adapter_profile": "amazon.reviews_export.v1",
            "idempotency_key": "pipeline-api:amazon:001",
        }
        created = client.post("/api/v1/business-pipeline/runs", headers=headers, json=payload)
        assert created.status_code == 200
        body = created.json()
        assert body["work_package_id"] == work_package_id
        assert body["adapter_profile"] == "amazon.reviews_export.v1"
        run_id = body["pipeline_run_id"]

        repeated = client.post("/api/v1/business-pipeline/runs", headers=headers, json=payload)
        assert repeated.status_code == 200
        assert repeated.json()["pipeline_run_id"] == run_id

        listed = client.get("/api/v1/business-pipeline/runs", headers=headers)
        assert listed.status_code == 200
        assert any(item["pipeline_run_id"] == run_id for item in listed.json())

        fetched = client.get(f"/api/v1/business-pipeline/runs/{run_id}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["pipeline_run_id"] == run_id

        reconciled = client.post(f"/api/v1/business-pipeline/runs/{run_id}/reconcile", headers=headers)
        assert reconciled.status_code == 200
        assert reconciled.json()["status"] == "BusinessAnalysis"

        package = client.get(f"/api/v1/business-pipeline/runs/{run_id}/return-package", headers=headers)
        assert package.status_code == 200
        assert package.json() is None


def test_pipeline_create_rejects_renderer_provider_and_path_injection(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        work_package_id = _seed_work_package(app)
        base = {
            "work_package_id": work_package_id,
            "adapter_profile": "amazon.reviews_export.v1",
            "idempotency_key": "pipeline-api:injection",
        }
        for field, value in {
            "model_id": "remote-model",
            "endpoint": "https://example.com",
            "workflow": {"class_type": "Anything"},
            "path": "C:/arbitrary",
            "command": "powershell.exe",
            "provider": "paid-cloud",
        }.items():
            rejected = client.post(
                "/api/v1/business-pipeline/runs",
                headers=headers,
                json={**base, field: value},
            )
            assert rejected.status_code == 422, field


def test_pipeline_routes_require_auth(tmp_path: Path) -> None:
    app, _headers = _app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/v1/business-pipeline/runs").status_code == 401
