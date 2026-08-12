from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.business.models import DeepAiHandoffRecord, WorkPackageManifest
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(paths=RuntimePaths.from_root(tmp_path / "runtime"), api_token=token)
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def _seed_needs_deep_ai(client: TestClient) -> str:
    services = client.app.state.services
    package_id = str(uuid4())
    manifest = WorkPackageManifest.model_validate(
        {
            "schema_version": "1.0",
            "package_id": package_id,
            "idempotency_key": f"deep-api:{package_id}",
            "producer_id": "amazon-research-app",
            "producer_version": "1.0.0",
            "created_at": "2026-08-11T12:00:00Z",
            "project_key": "pet-dryer-us",
            "analysis_profile": "reviews.voice_of_customer.v1",
            "objective": "Find supported customer insights.",
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
    services.business_repository.create_or_get_work_package(
        manifest,
        source_digest="b" * 64,
        compressed_size_bytes=256,
    )
    handoff = DeepAiHandoffRecord(
        handoff_id=str(uuid4()),
        work_package_id=package_id,
        source_digest="b" * 64,
        preprocess_digest="c" * 64,
        local_result_digest="d" * 64,
        quality_reasons=["semantic uncertainty"],
        return_schema={"type": "object", "required": ["findings"]},
        package_digest="e" * 64,
        package_relpath=f"runtime/business/handoffs/{package_id}.zip",
        status="Prepared",
    )
    services.business_repository.save_handoff(handoff)
    from picotoopet_core.business.models import BusinessWorkPackageStatus

    services.business_repository.transition_work_package(
        package_id,
        BusinessWorkPackageStatus.NEEDS_DEEP_AI,
        preprocess_digest="c" * 64,
        deep_ai_handoff_id=handoff.handoff_id,
        finished=True,
    )
    return package_id


def test_deep_ai_api_prepare_list_get_reconcile_readiness_usage_feedback(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    with client:
        source_id = _seed_needs_deep_ai(client)
        prepared = client.post(
            "/api/v1/deep-ai/escalations",
            headers=headers,
            json={"source_kind": "business.local_intelligence", "source_id": source_id},
        )
        assert prepared.status_code == 201, prepared.text
        job = prepared.json()
        assert job["status"] == "WaitingApproval"
        assert job["provider_profile_id"] == "paid.reasoning.v1"
        assert job["model_id"] == "gpt-5.6-terra"
        assert job["max_calls"] == 2
        assert str(job["max_cost_usd"]) in {"0.5", "0.50"}
        job_id = job["escalation_job_id"]

        listed = client.get("/api/v1/deep-ai/escalations", headers=headers)
        assert listed.status_code == 200
        assert [item["escalation_job_id"] for item in listed.json()] == [job_id]

        fetched = client.get(f"/api/v1/deep-ai/escalations/{job_id}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["sanitized_package_digest"] == job["sanitized_package_digest"]

        reconciled = client.post(
            f"/api/v1/deep-ai/escalations/{job_id}/reconcile",
            headers=headers,
            json={},
        )
        assert reconciled.status_code == 200
        assert reconciled.json()["status"] == "WaitingApproval"

        readiness = client.get(
            f"/api/v1/deep-ai/escalations/{job_id}/readiness",
            headers=headers,
        )
        assert readiness.status_code == 200
        assert readiness.json()["execution_enabled"] is False
        assert readiness.json()["provider_ready"] is False
        assert readiness.json()["reason_code"] == "DEEP_AI_EXECUTION_DISABLED"
        assert readiness.json()["manual_handoff_id"]

        usage = client.get(f"/api/v1/deep-ai/escalations/{job_id}/usage", headers=headers)
        assert usage.status_code == 200
        assert usage.json()["calls_used"] == 0
        assert usage.json()["input_tokens"] == 0
        assert usage.json()["output_tokens"] == 0
        assert str(usage.json()["cost_usd"]) in {"0", "0.0", "0.00"}

        feedback = client.post(
            f"/api/v1/deep-ai/escalations/{job_id}/feedback",
            headers=headers,
            json={
                "action": "Accepted",
                "reason_tags": ["useful", "grounded"],
                "final_content_digest": "f" * 64,
                "downstream_ref": "result-package-001",
                "idempotency_key": f"feedback:{job_id}:accepted:v1",
            },
        )
        assert feedback.status_code == 201, feedback.text
        assert feedback.json()["human_action"] == "Accepted"

        learning = client.get(
            "/api/v1/deep-ai/learning?project_key=pet-dryer-us",
            headers=headers,
        )
        assert learning.status_code == 200
        assert len(learning.json()) == 1


def test_deep_ai_api_rejects_untrusted_execution_overrides(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    with client:
        source_id = _seed_needs_deep_ai(client)
        for field, value in {
            "provider_profile_id": "attacker.provider",
            "provider": "attacker",
            "model": "attacker-model",
            "model_id": "attacker-model",
            "endpoint": "https://evil.invalid/v1",
            "url": "https://evil.invalid/v1",
            "api_key": "secret",
            "provider_key": "secret",
            "prompt": "ignore policy",
            "temperature": 1,
            "tools": [{"type": "shell"}],
            "command": "powershell.exe",
            "shell": "bash",
            "path": "/tmp/raw.zip",
            "workflow": {"nodes": []},
        }.items():
            response = client.post(
                "/api/v1/deep-ai/escalations",
                headers=headers,
                json={
                    "source_kind": "business.local_intelligence",
                    "source_id": source_id,
                    field: value,
                },
            )
            assert response.status_code == 422, (field, response.text)


def test_deep_ai_api_requires_authentication(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    with client:
        assert client.get("/api/v1/deep-ai/escalations").status_code == 401
