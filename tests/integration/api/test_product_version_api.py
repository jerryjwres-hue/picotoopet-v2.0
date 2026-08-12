"""Mac Core health exposes the canonical user-facing product version."""

from __future__ import annotations

from fastapi.testclient import TestClient

from picotoopet_core import __version__
from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def test_health_returns_canonical_product_version(tmp_path) -> None:
    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token="0123456789abcdef0123456789abcdef",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["version"] == __version__ == "2.3.22.1"
