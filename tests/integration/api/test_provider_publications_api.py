from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def make_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    token = "0123456789abcdef0123456789abcdef"
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=token,
    )
    return TestClient(create_app(settings)), {"Authorization": f"Bearer {token}"}


def test_publication_routes_require_auth_and_expose_only_read_and_prepare(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    with client:
        assert client.get("/api/v1/provider-publication-candidates").status_code == 401
        assert client.get(
            "/api/v1/provider-publication-candidates",
            headers=headers,
        ).json() == []

        openapi = client.get("/openapi.json").json()
        prepare_path = (
            "/api/v1/provider-commit-candidates/{commit_candidate_id}/publication/prepare"
        )
        assert prepare_path in openapi["paths"]
        operation = openapi["paths"][prepare_path]["post"]
        assert "requestBody" not in operation
        parameter_names = {parameter["name"] for parameter in operation["parameters"]}
        assert parameter_names == {"commit_candidate_id", "Idempotency-Key"}


def test_publication_prepare_requires_empty_body_and_fixed_path_identity(tmp_path: Path) -> None:
    client, headers = make_client(tmp_path)
    commit_id = "11111111-1111-1111-1111-111111111111"
    request_headers = {**headers, "Idempotency-Key": "api-publication-test"}
    with client:
        body_rejected = client.post(
            f"/api/v1/provider-commit-candidates/{commit_id}/publication/prepare",
            headers=request_headers,
            json={"base_ref": "main"},
        )
        assert body_rejected.status_code == 422
        assert body_rejected.json()["error"]["code"] == "VALIDATION_ERROR"

        missing = client.post(
            f"/api/v1/provider-commit-candidates/{commit_id}/publication/prepare",
            headers=request_headers,
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "PUBLICATION_NOT_FOUND"
