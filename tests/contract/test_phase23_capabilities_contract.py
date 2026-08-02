from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths


def test_capabilities_are_explicit_and_backward_compatible(tmp_path: Path) -> None:
    """Control Center 只能启用服务端明确声明的真实能力。"""

    settings = AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token="0123456789abcdef0123456789abcdef",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "2.3.0"
    assert body["features"]["durable_queue"] is True
    assert body["features"]["task_detail"] is False
    assert body["features"]["connector_contract_v1"] is True
    assert body["features"]["handoff_contract_v1"] is True
    assert body["contract_versions"] == {
        "connector": "1.0.0",
        "handoff_return": "1.0.0",
    }
