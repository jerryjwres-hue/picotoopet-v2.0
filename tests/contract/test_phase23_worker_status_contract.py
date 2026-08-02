from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths

_TOKEN = "0123456789abcdef0123456789abcdef"
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        paths=RuntimePaths.from_root(tmp_path / "runtime"),
        api_token=_TOKEN,
    )


def test_worker_status_is_truthful_when_worker_is_not_deployed(tmp_path: Path) -> None:
    """没有常驻 Worker 时必须显式报告 not_deployed，不能伪造在线。"""

    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/api/v1/workers/status", headers=_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "2.3.0"
    assert body["available"] is False
    assert body["state"] == "not_deployed"
    assert body["reason"] == "worker_runtime_not_installed"
    assert body["worker_id"] is None
    assert body["supported_task_types"] == []
    observed_at = datetime.fromisoformat(body["observed_at"].replace("Z", "+00:00"))
    assert observed_at.tzinfo is not None
    assert observed_at.astimezone(UTC) <= datetime.now(UTC)


def test_capabilities_advertise_status_but_not_worker_execution(tmp_path: Path) -> None:
    """状态查询能力可用不代表执行器已部署。"""

    with TestClient(create_app(_settings(tmp_path))) as client:
        response = client.get("/api/v1/capabilities")

    assert response.status_code == 200
    features = response.json()["features"]
    assert features["worker_status"] is True
    assert features["local_worker"] is False
