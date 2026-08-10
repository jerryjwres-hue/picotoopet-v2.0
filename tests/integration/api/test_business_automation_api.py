from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.business.upload import CHUNK_SIZE_BYTES
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def _client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=token,
    )
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def _prepare_payload(*, package_id: str, source_digest: str, total_size_bytes: int) -> dict[str, object]:
    return {
        "manifest": {
            "schema_version": "1.0",
            "package_id": package_id,
            "idempotency_key": f"api-business-{package_id}",
            "producer_id": "amazon-review-analyzer",
            "producer_version": "1.0.0",
            "created_at": "2026-08-10T12:00:00Z",
            "project_key": "pet-dryer-us",
            "analysis_profile": "reviews.voice_of_customer.v1",
            "objective": "Identify supported customer pain points.",
            "inputs": [
                {
                    "artifact_id": "reviews",
                    "path": "inputs/reviews.jsonl",
                    "media_type": "application/x-ndjson",
                    "sha256": "a" * 64,
                    "size_bytes": 20,
                    "record_key_field": "review_id",
                }
            ],
        },
        "source_digest": source_digest,
        "total_size_bytes": total_size_bytes,
    }


def test_business_routes_require_auth_and_prepare_contains_no_execution_fields(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    package_id = str(uuid4())
    payload = _prepare_payload(
        package_id=package_id,
        source_digest="b" * 64,
        total_size_bytes=100,
    )
    with client:
        assert client.get("/api/v1/business/work-packages").status_code == 401
        response = client.post(
            "/api/v1/business/work-packages/prepare",
            headers=headers,
            json=payload,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["work_package"]["work_package_id"] == package_id
        assert body["work_package"]["status"] == "Receiving"
        serialized = str(payload).lower()
        for forbidden in ("endpoint", "model_id", "system_prompt", "command", "executable", "tool_choice"):
            assert forbidden not in serialized


def test_business_chunk_body_is_bounded_to_four_mib(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    package_id = str(uuid4())
    source = b"x" * (CHUNK_SIZE_BYTES + 1)
    source_digest = hashlib.sha256(source).hexdigest()
    with client:
        prepared = client.post(
            "/api/v1/business/work-packages/prepare",
            headers=headers,
            json=_prepare_payload(
                package_id=package_id,
                source_digest=source_digest,
                total_size_bytes=len(source),
            ),
        )
        assert prepared.status_code == 200
        upload_id = prepared.json()["upload_session"]["upload_session_id"]
        response = client.put(
            f"/api/v1/business/upload-sessions/{upload_id}/chunks?offset=0",
            headers={**headers, "X-Chunk-SHA256": source_digest},
            content=source,
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "BUSINESS_CHUNK_SIZE_INVALID"


def test_finalize_incomplete_upload_fails_closed_and_keeps_receiving_fact(tmp_path: Path) -> None:
    client, headers = _client(tmp_path)
    package_id = str(uuid4())
    with client:
        prepared = client.post(
            "/api/v1/business/work-packages/prepare",
            headers=headers,
            json=_prepare_payload(
                package_id=package_id,
                source_digest="c" * 64,
                total_size_bytes=100,
            ),
        )
        upload_id = prepared.json()["upload_session"]["upload_session_id"]
        response = client.post(
            f"/api/v1/business/upload-sessions/{upload_id}/finalize",
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "UPLOAD_INCOMPLETE"
        state = client.get(
            f"/api/v1/business/work-packages/{package_id}",
            headers=headers,
        )
        assert state.status_code == 200
        assert state.json()["status"] == "Receiving"
