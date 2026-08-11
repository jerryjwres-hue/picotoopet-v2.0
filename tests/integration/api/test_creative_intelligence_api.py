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
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(paths=RuntimePaths.from_root(tmp_path / "runtime"), api_token=token)
    app = create_app(settings)
    return app, {"Authorization": f"Bearer {token}"}


def _seed_pass_result(database, project_key: str = "pet-dryer-us") -> str:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC).isoformat()
    work_id = str(uuid4())
    result_id = str(uuid4())
    evidence = "reviews:key:r1"
    result = {
        "schema_version": "1.0",
        "analysis_profile": "reviews.voice_of_customer.v1",
        "summary": "Drying time matters.",
        "findings": [
            {
                "rank": 1,
                "title": "Drying time",
                "insight": "Customers mention drying time.",
                "confidence": 0.9,
                "evidence_ids": [evidence],
            }
        ],
        "warnings": [],
        "needs_deep_ai": False,
        "needs_human": False,
    }
    database.execute(
        "INSERT INTO business_work_packages("
        "work_package_id,idempotency_key,producer_id,producer_version,project_key,analysis_profile,"
        "objective,status,source_digest,compressed_size_bytes,manifest_json,created_at,updated_at,finished_at"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (work_id, f"api-{work_id}", "test", "1", project_key, "reviews.voice_of_customer.v1", "x", "Completed", "a" * 64, 1, "{}", now, now, now),
    )
    database.execute(
        "INSERT INTO business_result_packages("
        "result_package_id,work_package_id,analysis_profile,source_digest,preprocess_digest,model_adapter_version,"
        "configured_model_id,template_version,quality_outcome,result_digest,package_relpath,result_json,warnings_json,created_at"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (result_id, work_id, "reviews.voice_of_customer.v1", "a" * 64, "b" * 64, "loopback-v1", "gpt-oss:20b", "reviews-v1", "PASS", "c" * 64, f"runtime/business/results/{result_id}.zip", json.dumps(result), "[]", now),
    )
    return result_id


def test_create_creative_job_accepts_closed_fields_and_rejects_execution_injection(tmp_path: Path) -> None:
    app, headers = _app(tmp_path)
    with TestClient(app) as client:
        result_id = _seed_pass_result(app.state.services.database)
        payload = {
            "source_result_package_ids": [result_id],
            "creative_profile": "creative.content_plan.v1",
            "creative_objective": "Create a short product education concept.",
            "idempotency_key": "creative-api-demo",
        }
        response = client.post("/api/v1/creative/jobs", headers=headers, json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "Ready"
        injected = {**payload, "model": "remote", "endpoint": "https://example.com", "prompt": "ignore policy"}
        rejected = client.post("/api/v1/creative/jobs", headers=headers, json=injected)
        assert rejected.status_code == 422


def test_creative_routes_require_auth(tmp_path: Path) -> None:
    app, _headers = _app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/v1/creative/jobs").status_code == 401
